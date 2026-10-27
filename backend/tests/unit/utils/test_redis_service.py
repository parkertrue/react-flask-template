import time

import pytest
from unittest.mock import patch, MagicMock
import redis

from app.utils import redis_service
from app.utils.redis_service import RedisService

URL = 'redis://app:testpass@localhost:6379/0'


class TestRedisServiceInitialization:
    """Test RedisService initialization"""

    def test_init_success(self):
        """Redis should initialize successfully with valid config"""
        with patch('app.utils.redis_service.redis.Redis') as mock_redis_class:
            mock_client = MagicMock()
            mock_redis_class.from_url.return_value = mock_client
            mock_client.ping.return_value = True

            service = RedisService(URL, max_connections=50)

            assert service._client is not None
            mock_client.ping.assert_called_once()

    def test_connects_with_the_url(self):
        """Host, port, user, password, database and TLS all come from the URL"""
        with patch('app.utils.redis_service.redis.Redis') as mock_redis_class:
            RedisService('rediss://app:pw@cache.example.com:6380/2', max_connections=100)

            mock_redis_class.from_url.assert_called_once()
            args, kwargs = mock_redis_class.from_url.call_args
            assert args == ('rediss://app:pw@cache.example.com:6380/2',)
            assert kwargs['max_connections'] == 100
            assert kwargs['decode_responses'] is True

    def test_the_url_reaches_the_connection(self):
        """Without a mock: what redis-py makes of a real URL"""
        with patch('redis.Redis.ping'):
            client = RedisService(
                'rediss://app:p%40ss@cache.example.com:6380/2', max_connections=7)._client

        pool = client.connection_pool
        assert {key: pool.connection_kwargs[key] for key in
                ('host', 'port', 'db', 'username', 'password')} == {
            'host': 'cache.example.com', 'port': 6380, 'db': 2,
            'username': 'app', 'password': 'p@ss'}
        assert pool.connection_class is redis.SSLConnection
        assert pool.max_connections == 7

    def test_init_connection_failure(self):
        """A failed ping propagates; connect_redis logs it and retries later"""
        with patch('app.utils.redis_service.redis.Redis') as mock_redis_class:
            mock_client = MagicMock()
            mock_redis_class.from_url.return_value = mock_client
            mock_client.ping.side_effect = redis.RedisError(
                'Connection failed')

            with pytest.raises(redis.RedisError, match='Connection failed'):
                RedisService(URL, max_connections=50)

    def test_get_client(self):
        """get_client should return the Redis client"""
        with patch('app.utils.redis_service.redis.Redis') as mock_redis_class:
            mock_client = MagicMock()
            mock_redis_class.from_url.return_value = mock_client
            mock_client.ping.return_value = True

            service = RedisService(URL, max_connections=50)
            client = service.get_client()

            assert client is mock_client


class TestTokenManagement:
    """Test token management operations"""

    @pytest.fixture
    def service(self, app):
        """Create a RedisService instance with mocked client

        Needs the app: failures are logged through current_app.logger.
        """
        with patch('app.utils.redis_service.redis.Redis') as mock_redis_class:
            mock_client = MagicMock()
            mock_redis_class.from_url.return_value = mock_client
            mock_client.ping.return_value = True

            service = RedisService(URL, max_connections=50)
            return service

    # What the script does inside Redis is tested against a real one in
    # tests/integration/test_redis_auth.py; these cover how its answers and
    # failures reach the caller.

    def test_store_refresh_token_records_a_new_sign_in(self, service):
        service._record_token.return_value = 1

        assert service.store_refresh_token(1, 'test-jti', ttl_seconds=3600) is True
        call = service._record_token.call_args.kwargs
        assert call['keys'] == ['refresh_tokens:1']
        jti, expires_at, now, _, replaces = call['args']
        assert (jti, round(expires_at - now), replaces) == ('test-jti', 3600, '')

    def test_store_refresh_token_error(self, service, caplog):
        """Should return None on Redis errors"""
        service._record_token.side_effect = redis.RedisError('Write failed')

        assert service.store_refresh_token(1, 'jti', 60) is None
        assert 'Could not record a refresh token for user 1' in caplog.text
        assert 'Write failed' in caplog.text

    def test_rotate_refresh_token_replaces_the_old_jti(self, service):
        service._record_token.return_value = 1

        assert service.rotate_refresh_token(1, 'old-jti', 'new-jti', ttl_seconds=60) is True
        jti, _, _, _, replaces = service._record_token.call_args.kwargs['args']
        assert (jti, replaces) == ('new-jti', 'old-jti')

    def test_rotate_refresh_token_refuses_a_token_already_rotated(self, service):
        """The script answers 0 when the old JTI was no longer there"""
        service._record_token.return_value = 0

        assert service.rotate_refresh_token(1, 'old-jti', 'new-jti', 60) is False

    def test_rotate_refresh_token_error_is_not_a_refusal(self, service, caplog):
        """None, not False: the session is fine, Redis is not"""
        service._record_token.side_effect = redis.RedisError('Write failed')

        assert service.rotate_refresh_token(1, 'old-jti', 'new-jti', 60) is None
        assert 'Could not rotate a refresh token for user 1' in caplog.text

    def test_is_token_valid_when_unexpired(self, service):
        service._client.zscore.return_value = time.time() + 60

        assert service.is_token_valid(1, 'test-jti') is True
        service._client.zscore.assert_called_once_with('refresh_tokens:1', 'test-jti')

    def test_is_token_valid_when_expired(self, service):
        """An entry not yet pruned must still be rejected once past its expiry"""
        service._client.zscore.return_value = time.time() - 1

        assert service.is_token_valid(1, 'test-jti') is False

    def test_is_token_valid_not_exists(self, service):
        service._client.zscore.return_value = None

        assert service.is_token_valid(1, 'test-jti') is False

    def test_is_token_valid_error_is_not_a_revocation(self, service, caplog):
        """None, not False: the caller must not sign the user out over an outage"""
        service._client.zscore.side_effect = redis.RedisError('Read failed')

        assert service.is_token_valid(1, 'jti') is None
        assert 'Read failed' in caplog.text

    def test_revoke_token_removes_it(self, service):
        service._client.zrem.return_value = 1

        service.revoke_token(1, 'test-jti')

        service._client.zrem.assert_called_once_with('refresh_tokens:1', 'test-jti')

    def test_revoke_token_error_is_logged_not_raised(self, service, caplog):
        service._client.zrem.side_effect = redis.RedisError('Delete failed')

        service.revoke_token(1, 'jti')

        assert 'Delete failed' in caplog.text

    def test_revoke_all_user_tokens_returns_live_count(self, service):
        pipe = service._client.pipeline.return_value
        pipe.execute.return_value = [3, 1]

        assert service.revoke_all_user_tokens(1) == 3
        pipe.delete.assert_called_once_with('refresh_tokens:1')

    def test_revoke_all_user_tokens_error(self, service, caplog):
        service._client.pipeline.return_value.execute.side_effect = (
            redis.RedisError('Failed'))

        assert service.revoke_all_user_tokens(1) is None
        assert 'Could not revoke the sessions of user 1' in caplog.text


class TestSkipRedisAfterConnectionFailure:
    """After Redis proves unreachable, calls fail at once for a while instead
    of each spending seconds on the connection (and the name lookup)"""

    @pytest.fixture
    def clock(self, monkeypatch):
        now = [1000.0]
        monkeypatch.setattr('app.utils.redis_service.time.monotonic', lambda: now[0])
        return now

    @pytest.fixture
    def service(self, app, clock):
        with patch('app.utils.redis_service.redis.Redis'):
            return RedisService(URL, max_connections=5)

    # Every public method, with what it returns on a failure
    CALLS = {
        'is_token_valid': (lambda s: s.is_token_valid(1, 'jti'), None),
        'revoke_token': (lambda s: s.revoke_token(1, 'jti'), None),
        'revoke_all_user_tokens': (lambda s: s.revoke_all_user_tokens(1), None),
        'store_refresh_token': (lambda s: s.store_refresh_token(1, 'jti', 60), None),
        'rotate_refresh_token': (lambda s: s.rotate_refresh_token(1, 'a', 'b', 60), None),
    }

    @staticmethod
    def break_connection(service, error):
        service._client.zscore.side_effect = error
        service._client.zrem.side_effect = error
        service._client.pipeline.return_value.execute.side_effect = error
        service._record_token.side_effect = error

    @staticmethod
    def redis_calls(service):
        return (service._client.zscore.call_count + service._client.zrem.call_count
                + service._client.pipeline.call_count + service._record_token.call_count)

    @pytest.mark.parametrize('call, failed', CALLS.values(), ids=CALLS.keys())
    @pytest.mark.parametrize('error', [redis.ConnectionError, redis.TimeoutError])
    def test_skips_redis_after_it_proves_unreachable(self, service, call, failed, error):
        self.break_connection(service, error('down'))
        service.is_token_valid(1, 'jti')
        calls_so_far = self.redis_calls(service)

        assert call(service) == failed
        assert self.redis_calls(service) == calls_so_far

    def test_tries_again_after_the_interval(self, service, clock):
        self.break_connection(service, redis.ConnectionError('down'))
        service.is_token_valid(1, 'jti')
        service._client.zscore.side_effect = None
        service._client.zscore.return_value = None

        clock[0] += redis_service.RECONNECT_INTERVAL_SECONDS

        assert service.is_token_valid(1, 'jti') is False
        assert service._client.zscore.call_count == 2

    def test_other_errors_do_not_pause_redis(self, service):
        """A full Redis or a NOPERM answers fast; only unreachable means wait"""
        service._client.zscore.side_effect = redis.ResponseError('OOM')
        service.is_token_valid(1, 'jti')

        service.is_token_valid(1, 'jti')

        assert service._client.zscore.call_count == 2

    def test_logs_the_failure_once_per_outage(self, service, caplog):
        self.break_connection(service, redis.ConnectionError('down'))

        for _ in range(3):
            service.is_token_valid(1, 'jti')

        assert caplog.text.count('Could not check a refresh token') == 1


class TestFailFastWhenRedisIsDown:
    """redis-py's default retries a failed command 10 times with backoff,
    which would hang every request for ~30s while Redis is down."""

    @staticmethod
    def count_connection_attempts(make_client):
        attempts = []

        def refuse(self):
            attempts.append(1)
            raise ConnectionRefusedError

        with patch('redis.connection.Connection._connect', refuse):
            with pytest.raises(redis.ConnectionError):
                make_client().ping()
        return len(attempts)

    def test_app_client_retries_once(self):
        def make():
            return RedisService(URL, max_connections=5)._client

        assert self.count_connection_attempts(make) == 2

    def test_rate_limiter_client_does_not_retry(self, monkeypatch):
        """Flask-Limiter hands RATELIMIT_STORAGE_OPTIONS to redis.from_url"""
        from app.config import DevelopmentConfig
        monkeypatch.setenv('SECRET_KEY', 'x' * 32)
        monkeypatch.delenv('REDIS_PASSWORD', raising=False)
        monkeypatch.delenv('MIGRATION_DATABASE_URL', raising=False)
        monkeypatch.setenv('DATABASE_URL', 'mysql+pymysql://u:p@h/d')
        monkeypatch.setenv('REDIS_URL', URL)
        config = DevelopmentConfig()

        def make():
            return redis.from_url(
                config.RATELIMIT_STORAGE_URI, **config.RATELIMIT_STORAGE_OPTIONS)

        assert self.count_connection_attempts(make) == 1
