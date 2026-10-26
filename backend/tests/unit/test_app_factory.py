import json
import sqlite3
from unittest.mock import patch

import pytest
import redis
from flask import abort, request
from flask_jwt_extended import create_refresh_token, decode_token
from sqlalchemy import event
from sqlalchemy.exc import IntegrityError, InterfaceError, OperationalError

import app as app_module
from app import create_app
from app.auth.models import TERMS_VERSION
from app.config import UnitTestConfig
from app.utils import redis_service
from app.utils.errors import SERVICE_UNAVAILABLE_MESSAGE
from app.utils.redis_service import get_redis_service


def build_app(monkeypatch, **overrides):
    """A fresh app from UnitTestConfig with some settings overridden."""
    config = UnitTestConfig()
    for key, value in overrides.items():
        setattr(config, key, value)
    monkeypatch.setattr(app_module, 'get_config', lambda: config)
    return create_app()


class TestProxyFix:
    """Rate limits key on request.remote_addr, so it must be the real client"""

    @pytest.fixture
    def remote_addr(self):
        def fetch(app, forwarded_for):
            @app.route('/_remote_addr')
            def show_remote_addr():
                return request.remote_addr

            response = app.test_client().get(
                '/_remote_addr',
                headers={'X-Forwarded-For': forwarded_for},
                environ_base={'REMOTE_ADDR': '172.18.0.5'},  # the proxy
            )
            return response.get_data(as_text=True)
        return fetch

    def test_behind_proxy_uses_forwarded_client(self, monkeypatch, remote_addr):
        app = build_app(monkeypatch, TRUSTED_PROXY_COUNT=1)

        assert remote_addr(app, '203.0.113.7') == '203.0.113.7'

    def test_ignores_client_spoofed_hops(self, monkeypatch, remote_addr):
        """nginx appends the real address; anything before it is client-supplied"""
        app = build_app(monkeypatch, TRUSTED_PROXY_COUNT=1)

        assert remote_addr(app, '1.2.3.4, 203.0.113.7') == '203.0.113.7'

    def test_without_proxy_ignores_header(self, monkeypatch, remote_addr):
        app = build_app(monkeypatch, TRUSTED_PROXY_COUNT=0)

        assert remote_addr(app, '203.0.113.7') == '172.18.0.5'


class TestRedisReconnect:
    """A worker that boots while Redis is down must pick it up once it's back"""

    @pytest.fixture
    def redis_down_at_boot(self, monkeypatch):
        clock = [1000.0]
        monkeypatch.setattr(redis_service.time, 'monotonic', lambda: clock[0])
        with patch('app.utils.redis_service.redis.Redis') as redis_class:
            redis_class.from_url.return_value.ping.side_effect = redis.ConnectionError
            app = build_app(
                monkeypatch, USES_SERVICES=True,
                REDIS_URL='redis://app:redispass@localhost:6379/0')
            yield app, redis_class, clock

    def test_boot_failure_leaves_no_service(self, redis_down_at_boot):
        app, _, _ = redis_down_at_boot

        assert app.extensions['redis_service'] is None

    def test_retries_after_interval(self, redis_down_at_boot):
        app, redis_class, clock = redis_down_at_boot
        redis_class.from_url.return_value.ping.side_effect = None
        clock[0] += redis_service.RECONNECT_INTERVAL_SECONDS

        with app.app_context():
            service = get_redis_service()

        assert service is not None
        assert app.extensions['redis_service'] is service

    def test_backs_off_between_attempts(self, redis_down_at_boot):
        app, redis_class, clock = redis_down_at_boot
        redis_class.from_url.return_value.ping.side_effect = None
        clock[0] += redis_service.RECONNECT_INTERVAL_SECONDS - 1

        with app.app_context():
            assert get_redis_service() is None
        assert redis_class.from_url.call_count == 1  # only the boot attempt

    def test_refresh_fails_closed_while_down(self, redis_down_at_boot):
        app, _, _ = redis_down_at_boot
        with app.app_context():
            token = create_refresh_token(identity='1')
            csrf = decode_token(token)['csrf']
        client = app.test_client()
        client.set_cookie('__Secure-refresh_token', token, path='/api/auth')

        response = client.post(
            '/api/auth/refresh', headers={'X-CSRF-REFRESH-TOKEN': csrf})

        assert response.status_code == 503
        assert response.get_json()['error']['code'] == 'SERVICE_UNAVAILABLE'


class TestCacheControl:
    """Tokens and private data must not be kept by any cache"""

    def test_api_responses_are_not_stored(self, client, sample_user, auth_headers):
        responses = [
            client.post('/api/auth/login',
                        json={'email': 'test@example.com', 'password': 'TestPassword123'}),
            client.get('/api/account', headers=auth_headers),
            client.get('/api/does-not-exist'),
        ]

        assert [r.headers.get('Cache-Control') for r in responses] == ['no-store'] * 3

    def test_a_route_can_set_its_own(self, monkeypatch):
        app = build_app(monkeypatch)

        @app.route('/_cached')
        def cached():
            return {}, 200, {'Cache-Control': 'max-age=60'}

        assert app.test_client().get('/_cached').headers['Cache-Control'] == 'max-age=60'


class TestJsonErrors:
    """Every error leaves the API as JSON the frontend can display"""

    @pytest.mark.parametrize('status, code', [
        (400, 'BAD_REQUEST'),
        (413, 'PAYLOAD_TOO_LARGE'),
        (415, 'UNSUPPORTED_MEDIA_TYPE'),
        (429, 'RATE_LIMITED'),
        # A status with no entry of its own, as a new feature might abort with
        (403, 'HTTP_ERROR'),
    ])
    def test_http_errors_are_json(self, monkeypatch, status, code):
        app = build_app(monkeypatch)

        @app.route('/_abort')
        def raise_status():
            abort(status)

        response = app.test_client().get('/_abort')

        assert response.status_code == status
        assert response.get_json()['error']['code'] == code

    def test_an_unlisted_status_is_named_by_werkzeug(self, monkeypatch):
        app = build_app(monkeypatch)

        @app.route('/_abort')
        def forbidden():
            abort(403)

        response = app.test_client().get('/_abort')

        assert response.get_json() == {
            'error': {'code': 'HTTP_ERROR', 'message': 'Forbidden'}}

    @pytest.mark.parametrize('body', ['null', '[]', '"text"'])
    def test_non_object_json_body_is_validation_error(self, client, body):
        response = client.post(
            '/api/auth/login', data=body, content_type='application/json')

        assert response.status_code == 422
        assert response.get_json()['error']['code'] == 'VALIDATION_ERROR'

    def test_non_json_content_type(self, client):
        response = client.post('/api/auth/login', data='email=a@b.com')

        assert response.status_code == 415
        assert response.get_json()['error']['code'] == 'UNSUPPORTED_MEDIA_TYPE'

    def test_oversized_body_is_rejected_before_parsing(self, client):
        response = client.post(
            '/api/auth/login', json={'email': 'a@b.com', 'password': 'x' * 20000})

        assert response.status_code == 413
        assert response.get_json()['error']['code'] == 'PAYLOAD_TOO_LARGE'

    def test_unhandled_exception_is_json_and_logged_once(self, monkeypatch, caplog):
        app = build_app(monkeypatch)
        app.config['PROPAGATE_EXCEPTIONS'] = False

        @app.route('/_crash')
        def crash():
            raise RuntimeError('boom')

        response = app.test_client().get('/_crash')

        assert response.status_code == 500
        assert response.get_json()['error']['code'] == 'INTERNAL_ERROR'
        tracebacks = [r for r in caplog.records if r.exc_info]
        assert len(tracebacks) == 1


class TestDatabaseOutage:
    """MySQL down or hung is an outage: 503, like Redis, so clients retry"""

    @pytest.fixture
    def raising(self, monkeypatch):
        def build(error):
            app = build_app(monkeypatch)
            app.config['PROPAGATE_EXCEPTIONS'] = False

            @app.route('/_query')
            def query():
                raise error

            return app.test_client().get('/_query')
        return build

    @pytest.mark.parametrize('error_class', [OperationalError, InterfaceError])
    def test_connection_errors_are_503_and_logged_once(self, raising, caplog, error_class):
        response = raising(error_class('SELECT 1', {}, Exception('2003 refused')))

        assert response.status_code == 503
        assert response.get_json()['error'] == {
            'code': 'SERVICE_UNAVAILABLE', 'message': SERVICE_UNAVAILABLE_MESSAGE}
        tracebacks = [r for r in caplog.records if r.exc_info]
        assert len(tracebacks) == 1
        assert tracebacks[0].getMessage() == 'Database unavailable'

    def test_other_database_errors_stay_500(self, raising):
        response = raising(IntegrityError('INSERT', {}, Exception('1062 duplicate')))

        assert response.status_code == 500
        assert response.get_json()['error']['code'] == 'INTERNAL_ERROR'

    def test_a_failed_write_logs_no_sql_parameters(self, app, client, caplog):
        """The logged exception text must not carry the row being written"""
        def database_down(conn, cursor, statement, parameters, context, executemany):
            if statement.startswith('INSERT'):
                raise sqlite3.OperationalError('database is locked')

        engine = app_module.db.engine
        event.listen(engine, 'before_cursor_execute', database_down)
        try:
            response = client.post('/api/auth/register', json={
                'email': 'stalled@example.com', 'password': 'TestPassword123',
                'terms_version': TERMS_VERSION})
        finally:
            event.remove(engine, 'before_cursor_execute', database_down)

        assert response.status_code == 503
        assert 'Database unavailable' in caplog.text
        assert 'INSERT INTO users' in caplog.text
        assert 'stalled@example.com' not in caplog.text
        assert 'scrypt:' not in caplog.text

    def test_user_lookup_during_an_outage_is_503(self, client, auth_token, monkeypatch):
        """Every @jwt_required route loads the user first, so this is where it fails"""
        def database_down(*args, **kwargs):
            raise OperationalError('SELECT', {}, Exception('2003 refused'))
        monkeypatch.setattr(app_module.db.session, 'get', database_down)

        response = client.get(
            '/api/account', headers={'Authorization': f'Bearer {auth_token}'})

        assert response.status_code == 503
        assert response.get_json()['error']['code'] == 'SERVICE_UNAVAILABLE'


class TestGlobalErrorHandlers:
    """Test global error handlers in Flask app."""

    def test_404_handler(self, client):
        """404 errors should return consistent error response."""
        response = client.get('/nonexistent-route')

        assert response.status_code == 404
        data = json.loads(response.data)
        assert data['error']['code'] == 'NOT_FOUND'
        assert 'not found' in data['error']['message'].lower()

    def test_404_on_api_route(self, client):
        """404 on API routes should return JSON error."""
        response = client.get('/api/nonexistent')

        assert response.status_code == 404
        assert response.get_json()['error']['code'] == 'NOT_FOUND'

    def test_405_handler(self, client):
        """405 errors should return consistent error response."""
        response = client.post('/api/health')

        assert response.status_code == 405
        data = json.loads(response.data)
        assert data['error']['code'] == 'METHOD_NOT_ALLOWED'
        assert 'not allowed' in data['error']['message'].lower()

        assert response.status_code == 405
        assert response.content_type == 'application/json'

    # The register route stands in for any route with a JSON body: it is
    # public and validates its body with a schema
    def test_pydantic_validation_error_handler(self, client):
        """Pydantic validation errors return 422 VALIDATION_ERROR."""
        response = client.post(
            '/api/auth/register',
            json={'email': 'not-an-email', 'password': 'TestPassword123', 'terms_version': TERMS_VERSION})

        assert response.status_code == 422
        assert response.get_json()['error']['code'] == 'VALIDATION_ERROR'

    def test_missing_json_body(self, client):
        """A JSON request with no body is malformed"""
        response = client.post('/api/auth/register', content_type='application/json')

        assert response.status_code == 400
        assert response.get_json()['error']['code'] == 'BAD_REQUEST'

    def test_malformed_json(self, client):
        """Malformed JSON should return 400."""
        response = client.post(
            '/api/auth/register',
            data='{"invalid": json}',
            content_type='application/json'
        )

        assert response.status_code == 400
        assert response.get_json()['error']['code'] == 'BAD_REQUEST'


# GET /api/account stands in for any route that needs a token: every app keeps it
class TestJWTErrorHandlers:
    """Test JWT-specific error handlers."""

    def test_missing_token_handler(self, client):
        """Missing JWT token should return 401 with AUTH_MISSING_TOKEN."""
        response = client.get('/api/account')

        assert response.status_code == 401
        data = response.get_json()
        assert data['error']['code'] == 'AUTH_MISSING_TOKEN'
        assert 'authentication required' in data['error']['message'].lower()

    def test_invalid_token_handler(self, client):
        """Invalid JWT token should return 401 with AUTH_INVALID_TOKEN."""
        response = client.get(
            '/api/account', headers={'Authorization': 'Bearer invalid-token-string'})

        assert response.status_code == 401
        assert response.get_json()['error']['code'] == 'AUTH_INVALID_TOKEN'

    def test_expired_token_handler(self, client, expired_token):
        """Expired JWT token should return 401 with AUTH_TOKEN_EXPIRED."""
        response = client.get(
            '/api/account', headers={'Authorization': f'Bearer {expired_token}'})

        assert response.status_code == 401
        data = response.get_json()
        assert data['error']['code'] == 'AUTH_TOKEN_EXPIRED'
        assert 'expired' in data['error']['message'].lower()

    @pytest.mark.parametrize('authorization, code', [
        # Not a Bearer header at all, so no token was sent
        ('InvalidFormat', 'AUTH_MISSING_TOKEN'),
        ('', 'AUTH_MISSING_TOKEN'),
        # A Bearer header without a token is a bad token
        ('Bearer', 'AUTH_INVALID_TOKEN'),
    ])
    def test_malformed_authorization_header(self, client, authorization, code):
        response = client.get('/api/account', headers={'Authorization': authorization})

        assert response.status_code == 401
        assert response.get_json()['error']['code'] == code


class TestErrorConsistency:
    """Every error, whichever handler made it, has the same JSON shape."""

    @pytest.mark.parametrize('method, url, kwargs, status, code', [
        ('GET', '/api/nonexistent', {}, 404, 'NOT_FOUND'),
        ('GET', '/api/account', {}, 401, 'AUTH_MISSING_TOKEN'),
        ('POST', '/api/auth/register', {'json': {'email': 'invalid'}}, 422, 'VALIDATION_ERROR'),
        ('POST', '/api/auth/login',
         {'json': {'email': 'nobody@example.com', 'password': 'WrongPassword123'}},
         401, 'INVALID_CREDENTIALS'),
    ])
    def test_errors_share_one_shape(self, client, method, url, kwargs, status, code):
        response = client.open(url, method=method, **kwargs)

        assert response.status_code == status
        assert response.content_type == 'application/json'
        error = response.get_json()['error']
        assert error['code'] == code
        # Codes are UPPER_SNAKE_CASE; messages are sentences a user can read
        assert error['code'].replace('_', '').isalpha() and error['code'].isupper()
        assert error['message'][0].isupper()
