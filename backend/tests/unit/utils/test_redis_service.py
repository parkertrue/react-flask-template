import hashlib
import json
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

            assert service._client is mock_client
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

    KEYS = ['refresh_tokens:{1}', 'refresh_tokens:{1}:sessions']

    def test_store_refresh_token_records_a_new_session(self, service):
        service._record_token.return_value = 1

        assert service.store_refresh_token(1, 'a-session', 'test-jti', ttl_seconds=3600,
                                           device='Firefox on Windows') is True
        call = service._record_token.call_args.kwargs
        assert call['keys'] == self.KEYS
        session_id, jti, expires_at, now, cap, replaces, device, signed_in_at = call['args']
        assert (session_id, jti, round(expires_at - now), cap, replaces, device) == (
            'a-session', 'test-jti', 3600, redis_service.MAX_SESSIONS_PER_USER, '', 'Firefox on Windows')
        assert signed_in_at == int(now)

    def test_store_refresh_token_error(self, service, caplog):
        """Should return None on Redis errors"""
        service._record_token.side_effect = redis.RedisError('Write failed')

        assert service.store_refresh_token(1, 'a-session', 'jti', 60, device='x') is None
        assert 'Could not record a refresh token for user 1' in caplog.text
        assert 'Write failed' in caplog.text

    def test_rotate_refresh_token_replaces_the_session_s_jti(self, service):
        service._record_token.return_value = 1

        assert service.rotate_refresh_token(1, 'a-session', 'old-jti', 'new-jti', ttl_seconds=60) is True
        session_id, jti, _, _, _, replaces, _, _ = service._record_token.call_args.kwargs['args']
        assert (session_id, jti, replaces) == ('a-session', 'new-jti', 'old-jti')

    def test_rotate_refresh_token_refuses_a_token_already_rotated(self, service):
        """The script answers 0 when the old JTI was no longer the session's"""
        service._record_token.return_value = 0

        assert service.rotate_refresh_token(1, 'a-session', 'old-jti', 'new-jti', 60) is False

    def test_rotate_refresh_token_error_is_not_a_refusal(self, service, caplog):
        """None, not False: the session is fine, Redis is not"""
        service._record_token.side_effect = redis.RedisError('Write failed')

        assert service.rotate_refresh_token(1, 'a-session', 'old-jti', 'new-jti', 60) is None
        assert 'Could not rotate a refresh token for user 1' in caplog.text

    @staticmethod
    def answer(service, expires_at, session):
        """What Redis answers for a session: its expiry, and its details"""
        pipe = service._client.pipeline.return_value
        pipe.execute.return_value = [expires_at, None if session is None else json.dumps(session)]
        return pipe

    def test_is_token_valid_for_the_session_s_current_token(self, service):
        pipe = self.answer(service, time.time() + 60, {'jti': 'test-jti'})

        assert service.is_token_valid(1, 'a-session', 'test-jti') is True
        pipe.zscore.assert_called_once_with(self.KEYS[0], 'a-session')
        pipe.hget.assert_called_once_with(self.KEYS[1], 'a-session')

    @pytest.mark.parametrize(('expires_in', 'session'), [
        (-1, {'jti': 'test-jti'}),
        (None, {'jti': 'test-jti'}),
        (60, {'jti': 'a-later-jti'}),
        (60, None),
    ], ids=['expired, not yet pruned', 'no such session', 'an older token', 'no details'])
    def test_is_token_valid_refuses(self, service, expires_in, session):
        self.answer(service, None if expires_in is None else time.time() + expires_in, session)

        assert service.is_token_valid(1, 'a-session', 'test-jti') is False

    def test_is_token_valid_error_is_not_a_revocation(self, service, caplog):
        """None, not False: the caller must not sign the user out over an outage"""
        service._client.pipeline.return_value.execute.side_effect = redis.RedisError('Read failed')

        assert service.is_token_valid(1, 'a-session', 'jti') is None
        assert 'Read failed' in caplog.text

    @pytest.mark.parametrize(('expires_in', 'live'), [(60, True), (-1, False), (None, False)],
                             ids=['live', 'expired, not yet pruned', 'none'])
    def test_is_session_live(self, service, expires_in, live):
        service._client.zscore.return_value = None if expires_in is None else time.time() + expires_in

        assert service.is_session_live(1, 'a-session') is live
        service._client.zscore.assert_called_once_with(self.KEYS[0], 'a-session')

    def test_is_session_live_error_is_not_an_end(self, service, caplog):
        """None, not False: the caller lets the token through an outage"""
        service._client.zscore.side_effect = redis.RedisError('Read failed')

        assert service.is_session_live(1, 'a-session') is None
        assert 'Could not check a session of user 1' in caplog.text

    @pytest.mark.parametrize(('expires_in', 'live'), [(60, True), (-1, False), (None, False)],
                             ids=['live', 'expired', 'none'])
    def test_revoke_session_removes_it_from_both_keys(self, service, expires_in, live):
        pipe = service._client.pipeline.return_value
        pipe.execute.return_value = [None if expires_in is None else time.time() + expires_in, 1, 1]

        assert service.revoke_session(1, 'a-session') is live
        pipe.zrem.assert_called_once_with(self.KEYS[0], 'a-session')
        pipe.hdel.assert_called_once_with(self.KEYS[1], 'a-session')

    def test_revoke_session_error_is_not_done(self, service, caplog):
        service._client.pipeline.return_value.execute.side_effect = redis.RedisError('Delete failed')

        assert service.revoke_session(1, 'a-session') is None
        assert 'Could not revoke a session of user 1' in caplog.text

    def test_revoke_token_error_is_logged_not_raised(self, service, caplog):
        service._client.pipeline.return_value.execute.side_effect = redis.RedisError('Delete failed')

        service.revoke_token(1, 'a-session')

        assert 'Delete failed' in caplog.text

    def test_revoke_all_user_tokens_returns_live_count(self, service):
        pipe = service._client.pipeline.return_value
        pipe.execute.return_value = [3, 2]

        assert service.revoke_all_user_tokens(1) == 3
        pipe.delete.assert_called_once_with(*self.KEYS)

    def test_revoke_all_user_tokens_error(self, service, caplog):
        service._client.pipeline.return_value.execute.side_effect = (
            redis.RedisError('Failed'))

        assert service.revoke_all_user_tokens(1) is None
        assert 'Could not revoke the sessions of user 1' in caplog.text

    def test_list_sessions_live_ones_most_recently_active_first(self, service):
        pipe = service._client.pipeline.return_value
        details = {
            'older': {'jti': 'j1', 'device': 'Firefox on Windows', 'signed_in_at': 100, 'last_active_at': 200},
            'newer': {'jti': 'j2', 'device': 'Safari on iOS', 'signed_in_at': 150, 'last_active_at': 300},
            'expired': {'jti': 'j3', 'device': 'Chrome on Linux', 'signed_in_at': 1, 'last_active_at': 2},
        }
        # Live per the sorted set; 'gone' has no details (a race with an end)
        pipe.execute.return_value = [['older', 'newer', 'gone'],
                                     {key: json.dumps(value) for key, value in details.items()}]

        assert service.list_sessions(1) == [
            {'id': 'newer', 'device': 'Safari on iOS', 'signed_in_at': 150, 'last_active_at': 300},
            {'id': 'older', 'device': 'Firefox on Windows', 'signed_in_at': 100, 'last_active_at': 200},
        ]
        assert pipe.zrangebyscore.call_args.args[0] == self.KEYS[0]
        pipe.hgetall.assert_called_once_with(self.KEYS[1])

    def test_list_sessions_error(self, service, caplog):
        service._client.pipeline.return_value.execute.side_effect = redis.RedisError('Read failed')

        assert service.list_sessions(1) is None
        assert 'Could not list the sessions of user 1' in caplog.text


class TestUsedLinks:
    """An emailed link, once used, is kept as a hash of its token so it
    works once (what the route does with the answers: tests/unit/auth)"""

    TOKEN = 'a.link.token'
    KEY = f'used_links:{hashlib.sha256(TOKEN.encode()).hexdigest()}'

    @pytest.fixture
    def service(self, app):
        with patch('app.utils.redis_service.redis.Redis'):
            return RedisService(URL, max_connections=5)

    def test_claiming_sets_the_tokens_hash_once_for_its_lifetime(self, service):
        service._client.set.return_value = True

        assert service.claim_link(self.TOKEN, ttl_seconds=86400) is True
        service._client.set.assert_called_once_with(self.KEY, 1, nx=True, ex=86400)

    def test_a_link_claimed_before_is_refused(self, service):
        """SET NX answers None when the key is there"""
        service._client.set.return_value = None

        assert service.claim_link(self.TOKEN, ttl_seconds=86400) is False

    def test_a_failed_claim_is_not_a_refusal(self, service, caplog):
        """None, not False: the link may be unused, Redis is not answering"""
        service._client.set.side_effect = redis.RedisError('OOM')

        assert service.claim_link(self.TOKEN, ttl_seconds=86400) is None
        assert 'Could not mark a link used' in caplog.text
        assert self.TOKEN not in caplog.text

    def test_releasing_deletes_the_tokens_hash(self, service):
        service.release_link(self.TOKEN)

        service._client.delete.assert_called_once_with(self.KEY)

    def test_a_failed_release_is_logged(self, service, caplog):
        service._client.delete.side_effect = redis.RedisError('OOM')

        service.release_link(self.TOKEN)

        assert 'Could not release a used link' in caplog.text


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
        'is_token_valid': (lambda s: s.is_token_valid(1, 'sid', 'jti'), None),
        'revoke_token': (lambda s: s.revoke_token(1, 'sid'), None),
        'revoke_session': (lambda s: s.revoke_session(1, 'sid'), None),
        'is_session_live': (lambda s: s.is_session_live(1, 'sid'), None),
        'revoke_all_user_tokens': (lambda s: s.revoke_all_user_tokens(1), None),
        'list_sessions': (lambda s: s.list_sessions(1), None),
        'store_refresh_token': (lambda s: s.store_refresh_token(1, 'sid', 'jti', 60, device='x'), None),
        'rotate_refresh_token': (lambda s: s.rotate_refresh_token(1, 'sid', 'a', 'b', 60), None),
        'claim_link': (lambda s: s.claim_link('token', 60), None),
        'release_link': (lambda s: s.release_link('token'), None),
    }

    @staticmethod
    def break_connection(service, error):
        service._client.zscore.side_effect = error
        service._client.zrem.side_effect = error
        service._client.pipeline.return_value.execute.side_effect = error
        service._record_token.side_effect = error
        service._client.set.side_effect = error
        service._client.delete.side_effect = error

    @staticmethod
    def redis_calls(service):
        return (service._client.zscore.call_count + service._client.zrem.call_count
                + service._client.pipeline.call_count + service._record_token.call_count
                + service._client.set.call_count + service._client.delete.call_count)

    @pytest.mark.parametrize('call, failed', CALLS.values(), ids=CALLS.keys())
    @pytest.mark.parametrize('error', [redis.ConnectionError, redis.TimeoutError])
    def test_skips_redis_after_it_proves_unreachable(self, service, call, failed, error):
        self.break_connection(service, error('down'))
        service.is_token_valid(1, 'sid', 'jti')
        calls_so_far = self.redis_calls(service)

        assert call(service) == failed
        assert self.redis_calls(service) == calls_so_far

    def test_tries_again_after_the_interval(self, service, clock):
        self.break_connection(service, redis.ConnectionError('down'))
        service.is_token_valid(1, 'sid', 'jti')
        execute = service._client.pipeline.return_value.execute
        execute.side_effect = None
        execute.return_value = [None, None]

        clock[0] += redis_service.RECONNECT_INTERVAL_SECONDS

        assert service.is_token_valid(1, 'sid', 'jti') is False
        assert execute.call_count == 2

    def test_other_errors_do_not_pause_redis(self, service):
        """A full Redis or a NOPERM answers fast; only unreachable means wait"""
        execute = service._client.pipeline.return_value.execute
        execute.side_effect = redis.ResponseError('OOM')
        service.is_token_valid(1, 'sid', 'jti')

        service.is_token_valid(1, 'sid', 'jti')

        assert execute.call_count == 2

    def test_logs_the_failure_once_per_outage(self, service, caplog):
        self.break_connection(service, redis.ConnectionError('down'))

        for _ in range(3):
            service.is_token_valid(1, 'sid', 'jti')

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
