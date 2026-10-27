import json
import time
from datetime import timedelta
from unittest.mock import patch

import jwt
import pytest
from flask_jwt_extended import create_refresh_token, decode_token
from sqlalchemy import select, func

from app.auth import routes as auth_routes
from app.auth.models import TERMS_VERSION, User
from app.utils.errors import SERVICE_UNAVAILABLE_MESSAGE
from app.utils.passwords import verify_password


class TestRegisterEndpoint:
    """Test suite for POST /api/auth/register endpoint."""

    def test_register_success(self, client, db):
        """Valid registration should create user and return 201."""
        payload = {
            'email': 'newuser@example.com',
            'password': 'ValidPass123',
            'terms_version': TERMS_VERSION
        }

        response = client.post(
            '/api/auth/register',
            data=json.dumps(payload),
            content_type='application/json'
        )

        assert response.status_code == 201
        data = json.loads(response.data)
        assert data['message'] == 'User created'

    def test_register_creates_user_in_database(self, client, db):
        """Registration should persist user to database."""
        initial_count = db.session.scalar(
            select(func.count()).select_from(User)
        )

        payload = {
            'email': 'dbuser@example.com',
            'password': 'ValidPass123',
            'terms_version': TERMS_VERSION
        }

        response = client.post(
            '/api/auth/register',
            data=json.dumps(payload),
            content_type='application/json'
        )

        assert response.status_code == 201

        new_count = db.session.scalar(
            select(func.count()).select_from(User)
        )
        assert new_count == initial_count + 1

        # Verify user exists with correct email
        user = db.session.execute(
            select(User).where(User.email == 'dbuser@example.com')
        ).scalar_one_or_none()
        assert user is not None
        assert user.email == 'dbuser@example.com'

    def test_register_hashes_password(self, client, db):
        """Registration should hash the password."""
        payload = {
            'email': 'hashtest@example.com',
            'password': 'PlainTextPass123',
            'terms_version': TERMS_VERSION
        }

        response = client.post(
            '/api/auth/register',
            data=json.dumps(payload),
            content_type='application/json'
        )

        assert response.status_code == 201

        user = db.session.execute(
            select(User).where(User.email == 'hashtest@example.com')
        ).scalar_one()

        assert user.password_hash != 'PlainTextPass123'
        assert user.check_password('PlainTextPass123')

    def test_register_records_the_terms_accepted_and_when(self, client, db):
        response = client.post('/api/auth/register', json={
            'email': 'terms@example.com', 'password': 'ValidPass123',
            'terms_version': TERMS_VERSION})

        assert response.status_code == 201
        user = db.session.execute(
            select(User).where(User.email == 'terms@example.com')).scalar_one()
        assert user.terms_version == TERMS_VERSION
        assert user.terms_accepted_at == user.created_at

    @pytest.mark.parametrize('version', [TERMS_VERSION - 1, TERMS_VERSION + 1])
    def test_register_refuses_terms_other_than_the_current_ones(self, client, db, version):
        """A page loaded before the terms changed offered the old ones"""
        response = client.post('/api/auth/register', json={
            'email': 'terms@example.com', 'password': 'ValidPass123',
            'terms_version': version})

        assert response.status_code == 409
        assert response.get_json()['error']['code'] == 'TERMS_OUTDATED'
        assert db.session.scalar(select(func.count()).select_from(User)) == 0

    def test_register_duplicate_email(self, client, sample_user):
        """Registering with existing email should return 409."""
        payload = {
            'email': 'test@example.com',  # sample_user email
            'password': 'DifferentPass123',
            'terms_version': TERMS_VERSION
        }

        response = client.post(
            '/api/auth/register',
            data=json.dumps(payload),
            content_type='application/json'
        )

        assert response.status_code == 409
        data = json.loads(response.data)
        assert data['error']['code'] == 'EMAIL_ALREADY_REGISTERED'
        assert 'already registered' in data['error']['message'].lower()

    @pytest.mark.parametrize('payload', [
        {'email': 'not-an-email', 'password': 'ValidPass123', 'terms_version': TERMS_VERSION},
        {'password': 'ValidPass123', 'terms_version': TERMS_VERSION},
        {'email': 'test@example.com', 'terms_version': TERMS_VERSION},
        {'email': 'test@example.com', 'password': 'ValidPass123'},
        {'email': 'test@example.com', 'password': 'ValidPass123', 'terms_version': str(TERMS_VERSION)},
    ])
    def test_invalid_body_is_validation_error_and_stores_nothing(self, client, db, payload):
        response = client.post('/api/auth/register', json=payload)

        assert response.status_code == 422
        assert response.get_json()['error']['code'] == 'VALIDATION_ERROR'
        assert db.session.scalar(select(func.count()).select_from(User)) == 0

    def test_register_race_is_a_conflict_not_a_crash(self, client, db, monkeypatch):
        """Another request registers the email after the existence check
        (a double submit): the unique index rejects this one, which must be
        a 409 rather than an unhandled IntegrityError."""
        set_password = User.set_password

        def register_concurrently(user, password):
            rival = User(email=user.email)
            set_password(rival, password)
            db.session.add(rival)
            db.session.commit()
            set_password(user, password)

        monkeypatch.setattr(User, 'set_password', register_concurrently)

        response = client.post('/api/auth/register', json={
            'email': 'race@example.com', 'password': 'ValidPass123', 'terms_version': TERMS_VERSION})

        assert response.status_code == 409
        assert response.get_json()['error']['code'] == 'EMAIL_ALREADY_REGISTERED'
        assert db.session.scalar(select(func.count()).select_from(User)) == 1

    @pytest.mark.parametrize('password', [
        'Short1',
        'nouppercase123',
        'NOLOWERCASE123',
        'NoNumbersHere',
    ], ids=['too short', 'no uppercase', 'no lowercase', 'no number'])
    def test_register_refuses_a_weak_password(self, client, db, password):
        response = client.post('/api/auth/register', json={
            'email': 'test@example.com', 'password': password})

        assert response.status_code == 422
        assert response.get_json()['error']['code'] == 'VALIDATION_ERROR'
        assert db.session.scalar(select(func.count()).select_from(User)) == 0

    def test_register_extra_fields(self, client):
        """Extra fields should be rejected."""
        payload = {
            'email': 'test@example.com',
            'password': 'ValidPass123',
            'extra_field': 'should fail',
            'terms_version': TERMS_VERSION
        }

        response = client.post(
            '/api/auth/register',
            data=json.dumps(payload),
            content_type='application/json'
        )

        assert response.status_code == 422

    def test_register_invalid_json(self, client, db):
        """A body that is not JSON at all is malformed: 400, not 422"""
        response = client.post(
            '/api/auth/register',
            data='not valid json{',
            content_type='application/json'
        )

        assert response.status_code == 400
        assert response.get_json()['error']['code'] == 'BAD_REQUEST'
        assert db.session.scalar(select(func.count()).select_from(User)) == 0


class TestLoginEndpoint:
    """Test suite for POST /api/auth/login endpoint."""

    def test_login_success(self, client, sample_user):
        """Valid credentials should return access token and 200."""
        payload = {
            'email': 'test@example.com',
            'password': 'TestPassword123'
        }

        response = client.post(
            '/api/auth/login',
            data=json.dumps(payload),
            content_type='application/json'
        )

        assert response.status_code == 200
        data = json.loads(response.data)
        assert 'access_token' in data
        assert 'refresh_csrf' in data
        assert len(data['access_token']) > 0

    def test_login_sets_refresh_cookie(self, client, sample_user):
        """Login should set refresh token as HttpOnly cookie."""
        payload = {
            'email': 'test@example.com',
            'password': 'TestPassword123'
        }

        response = client.post(
            '/api/auth/login',
            data=json.dumps(payload),
            content_type='application/json'
        )

        assert response.status_code == 200

        cookies = response.headers.getlist('Set-Cookie')
        # Only the refresh cookie, HttpOnly. The CSRF value travels in the
        # body, so no script-readable CSRF cookie is set.
        assert len(cookies) == 1
        assert cookies[0].startswith('__Secure-refresh_token=')
        assert 'HttpOnly' in cookies[0]
        # Browsers drop a __Secure- cookie that isn't Secure
        assert 'Secure;' in cookies[0]

    def test_login_wrong_password(self, client, sample_user):
        """Wrong password should return 401."""
        payload = {
            'email': 'test@example.com',
            'password': 'WrongPassword123'
        }

        response = client.post(
            '/api/auth/login',
            data=json.dumps(payload),
            content_type='application/json'
        )

        assert response.status_code == 401
        data = json.loads(response.data)
        assert data['error']['code'] == 'INVALID_CREDENTIALS'

    def test_login_nonexistent_user(self, client):
        """Login with non-existent email should return 401."""
        payload = {
            'email': 'nonexistent@example.com',
            'password': 'SomePassword123'
        }

        response = client.post(
            '/api/auth/login',
            data=json.dumps(payload),
            content_type='application/json'
        )

        assert response.status_code == 401
        data = json.loads(response.data)
        assert data['error']['code'] == 'INVALID_CREDENTIALS'

    def test_login_nonexistent_user_still_hashes(self, client):
        """Skipping the hash would make unknown emails measurably faster."""
        payload = {
            'email': 'nonexistent@example.com',
            'password': 'SomePassword123'
        }

        with patch('app.auth.routes.verify_password',
                   wraps=verify_password) as check:
            response = client.post('/api/auth/login', json=payload)

        assert response.status_code == 401
        check.assert_called_once_with(
            auth_routes.DUMMY_PASSWORD_HASH, 'SomePassword123')

    def test_login_invalid_email_format(self, client):
        """Invalid email format should return 422."""
        payload = {
            'email': 'not-an-email',
            'password': 'SomePassword123'
        }

        response = client.post(
            '/api/auth/login',
            data=json.dumps(payload),
            content_type='application/json'
        )

        assert response.status_code == 422

    def test_login_missing_email(self, client):
        """Missing email should return 422."""
        payload = {
            'password': 'SomePassword123'
        }

        response = client.post(
            '/api/auth/login',
            data=json.dumps(payload),
            content_type='application/json'
        )

        assert response.status_code == 422

    def test_login_missing_password(self, client):
        """Missing password should return 422."""
        payload = {
            'email': 'test@example.com'
        }

        response = client.post(
            '/api/auth/login',
            data=json.dumps(payload),
            content_type='application/json'
        )

        assert response.status_code == 422

    def test_login_case_sensitive_password(self, client, sample_user):
        """Password should be case-sensitive."""
        payload = {
            'email': 'test@example.com',
            'password': 'tESTpASSWORD123'  # Wrong case, but within the rules
        }

        response = client.post(
            '/api/auth/login',
            data=json.dumps(payload),
            content_type='application/json'
        )

        assert response.status_code == 401

LOGIN_PAYLOAD = {'email': 'test@example.com', 'password': 'TestPassword123'}
DAY = 24 * 60 * 60
SESSION_LIFETIME = 30 * DAY  # JWT_REFRESH_TOKEN_EXPIRES
IDLE_TIMEOUT = 7 * DAY  # SESSION_IDLE_TIMEOUT


def refresh_claims(client):
    """The claims of the refresh cookie the client now holds"""
    cookie = client.get_cookie('__Secure-refresh_token', path='/api/auth').value
    return decode_token(cookie, allow_expired=True)


def set_refresh_token(app, client, user, fake_redis, auth_time, expires_in):
    """Give the client a recorded refresh token for a session that began at
    auth_time, expiring expires_in seconds from now; return its CSRF header."""
    with app.app_context():
        token = create_refresh_token(
            identity=str(user.id), additional_claims={'auth_time': auth_time},
            expires_delta=timedelta(seconds=expires_in))
        claims = decode_token(token, allow_expired=True)
    fake_redis.store_refresh_token(user.id, claims['jti'], 60)
    client.set_cookie('__Secure-refresh_token', token, path='/api/auth')
    return {'X-CSRF-REFRESH-TOKEN': claims['csrf']}


def login(client):
    """Log in as sample_user; return the refresh CSRF header to send back."""
    response = client.post('/api/auth/login', json=LOGIN_PAYLOAD)
    assert response.status_code == 200
    return {'X-CSRF-REFRESH-TOKEN': response.get_json()['refresh_csrf']}


class TestRefreshEndpoint:
    """Test suite for POST /api/auth/refresh endpoint."""

    def test_refresh_returns_working_access_token(self, client, sample_user, fake_redis):
        csrf = login(client)

        response = client.post('/api/auth/refresh', headers=csrf)

        assert response.status_code == 200
        token = response.get_json()['access_token']
        account = client.get('/api/account', headers={'Authorization': f'Bearer {token}'})
        assert account.status_code == 200

    def test_refresh_rotates_csrf_token(self, client, sample_user, fake_redis):
        """Each refresh token carries its own CSRF value; clients must store the new one"""
        csrf = login(client)

        response = client.post('/api/auth/refresh', headers=csrf)

        new_csrf = response.get_json()['refresh_csrf']
        assert new_csrf != csrf['X-CSRF-REFRESH-TOKEN']

    def test_second_refresh_requires_rotated_csrf(self, client, sample_user, fake_redis):
        csrf = login(client)
        first = client.post('/api/auth/refresh', headers=csrf)
        new_csrf = {'X-CSRF-REFRESH-TOKEN': first.get_json()['refresh_csrf']}

        stale = client.post('/api/auth/refresh', headers=csrf)
        fresh = client.post('/api/auth/refresh', headers=new_csrf)

        assert stale.status_code == 401
        assert fresh.status_code == 200

    def test_concurrent_refreshes_of_one_token_yield_one_session(
            self, app, client, sample_user, fake_redis, monkeypatch):
        """Two requests can both pass the blocklist check before either rotates;
        the rotation itself must still let only the first one through"""
        csrf = login(client)
        cookie = client.get_cookie('__Secure-refresh_token', path='/api/auth').value
        replay = app.test_client(use_cookies=False)
        headers = {**csrf, 'Cookie': f'__Secure-refresh_token={cookie}'}
        # As both requests saw it: the token was still live when checked
        monkeypatch.setattr(fake_redis, 'is_token_valid', lambda *args: True)

        first = replay.post('/api/auth/refresh', headers=headers)
        second = replay.post('/api/auth/refresh', headers=headers)

        assert first.status_code == 200
        assert second.status_code == 401
        assert second.get_json()['error']['code'] == 'AUTH_TOKEN_REVOKED'
        assert len(fake_redis.tokens) == 1

    def test_refresh_revokes_previous_token(self, client, sample_user, fake_redis):
        csrf = login(client)
        (old,) = fake_redis.tokens

        client.post('/api/auth/refresh', headers=csrf)

        assert old not in fake_redis.tokens
        assert len(fake_redis.tokens) == 1

    def test_login_starts_the_session_clock(self, client, sample_user, fake_redis):
        before = int(time.time())
        login(client)

        claims = refresh_claims(client)

        after = int(time.time())
        assert before <= claims['auth_time'] <= after
        assert before + IDLE_TIMEOUT <= claims['exp'] <= after + IDLE_TIMEOUT
        assert fake_redis.ttls[claims['jti']] == IDLE_TIMEOUT

    def test_refresh_extends_an_active_session_by_the_idle_timeout(
            self, app, client, sample_user, fake_redis):
        """Each use buys another idle window, not the rest of the 30 days"""
        auth_time = int(time.time()) - 20 * DAY
        csrf = set_refresh_token(app, client, sample_user, fake_redis, auth_time,
                                 expires_in=DAY)
        before = int(time.time())

        response = client.post('/api/auth/refresh', headers=csrf)

        assert response.status_code == 200
        claims = refresh_claims(client)
        assert claims['auth_time'] == auth_time
        assert before + IDLE_TIMEOUT <= claims['exp'] <= int(time.time()) + IDLE_TIMEOUT
        assert fake_redis.ttls[claims['jti']] == IDLE_TIMEOUT

    def test_refresh_after_the_idle_timeout_is_refused(
            self, app, client, sample_user, fake_redis):
        """A session well within its 30 days, left unused past its window"""
        auth_time = int(time.time()) - 10 * DAY
        csrf = set_refresh_token(app, client, sample_user, fake_redis, auth_time,
                                 expires_in=-60)

        response = client.post('/api/auth/refresh', headers=csrf)

        assert response.status_code == 401
        assert response.get_json()['error']['code'] == 'AUTH_TOKEN_EXPIRED'

    def test_refresh_never_extends_the_session_past_its_lifetime(
            self, app, client, sample_user, fake_redis):
        """Near the end of its 30 days, a rotated token expires when the
        session does, not a whole idle window from now"""
        auth_time = int(time.time()) - 29 * DAY
        csrf = set_refresh_token(app, client, sample_user, fake_redis, auth_time,
                                 expires_in=DAY)

        response = client.post('/api/auth/refresh', headers=csrf)

        assert response.status_code == 200
        claims = refresh_claims(client)
        assert claims['auth_time'] == auth_time
        assert claims['exp'] == auth_time + SESSION_LIFETIME
        # Redis keeps it no longer either: at the session cap, the oldest
        # score is evicted first, which must be this ending session
        assert DAY - 60 <= fake_redis.ttls[claims['jti']] <= DAY

    def test_refresh_after_the_session_lifetime_is_refused(
            self, app, client, sample_user, fake_redis):
        """The last token of a chain, past its end: the user must log in again"""
        auth_time = int(time.time()) - SESSION_LIFETIME - 60
        csrf = set_refresh_token(app, client, sample_user, fake_redis, auth_time,
                                 expires_in=-60)

        response = client.post('/api/auth/refresh', headers=csrf)

        assert response.status_code == 401
        assert response.get_json()['error']['code'] == 'AUTH_TOKEN_EXPIRED'

    def test_refresh_without_csrf_header(self, client, sample_user, fake_redis):
        login(client)

        response = client.post('/api/auth/refresh')

        assert response.status_code == 401

    def test_refresh_without_cookie(self, client):
        response = client.post('/api/auth/refresh')

        assert response.status_code == 401
        assert response.get_json()['error']['code'] == 'AUTH_MISSING_TOKEN'

    def test_refresh_fails_closed_without_redis(self, app, client, sample_user, monkeypatch):
        """With no Redis there is no allowlist: refuse the token, but as an
        outage the client retries, not a revocation that signs the user out"""
        csrf = login(client)
        monkeypatch.setitem(app.extensions, 'redis_service', None)

        response = client.post('/api/auth/refresh', headers=csrf)

        assert response.status_code == 503
        assert response.get_json()['error'] == {
            'code': 'SERVICE_UNAVAILABLE', 'message': SERVICE_UNAVAILABLE_MESSAGE}

    def test_refresh_fails_closed_when_the_check_fails(
            self, client, sample_user, fake_redis, monkeypatch):
        csrf = login(client)
        monkeypatch.setattr(fake_redis, 'is_token_valid', lambda user_id, jti: None)

        response = client.post('/api/auth/refresh', headers=csrf)

        assert response.status_code == 503
        assert response.get_json()['error']['code'] == 'SERVICE_UNAVAILABLE'
        assert len(fake_redis.tokens) == 1  # nothing rotated

    def test_refresh_for_a_deleted_user_is_rejected(
            self, client, sample_user, fake_redis, db):
        """The session outlives the account only until the next request"""
        csrf = login(client)
        db.session.delete(sample_user)
        db.session.commit()

        response = client.post('/api/auth/refresh', headers=csrf)

        assert response.status_code == 401
        assert response.get_json()['error']['code'] == 'AUTH_INVALID_TOKEN'


class TestLogoutEndpoint:
    """Test suite for POST /api/auth/logout and /api/auth/logout-all."""

    def test_logout_revokes_token_and_clears_cookies(self, client, sample_user, fake_redis):
        csrf = login(client)

        response = client.post('/api/auth/logout', headers=csrf)

        assert response.status_code == 200
        assert response.get_json()['message'] == 'Logged out'
        assert fake_redis.tokens == set()
        cleared = response.headers.getlist('Set-Cookie')
        assert any(c.startswith('__Secure-refresh_token=;') for c in cleared)

    def test_refresh_after_logout_is_rejected(self, client, sample_user, fake_redis):
        csrf = login(client)
        refresh_cookie = client.get_cookie('__Secure-refresh_token', path='/api/auth').value
        client.post('/api/auth/logout', headers=csrf)

        # Replay the logged-out token, as a stolen cookie would be
        client.set_cookie('__Secure-refresh_token', refresh_cookie, path='/api/auth')
        response = client.post('/api/auth/refresh', headers=csrf)

        assert response.status_code == 401
        assert response.get_json()['error']['code'] == 'AUTH_TOKEN_REVOKED'

    def test_clear_cookies_expires_refresh_cookies(self, client, sample_user, fake_redis):
        login(client)

        response = client.post('/api/auth/clear-cookies', json={})

        assert response.status_code == 200
        cleared = response.headers.getlist('Set-Cookie')
        assert any(c.startswith('__Secure-refresh_token=;') for c in cleared)
        assert client.get_cookie('__Secure-refresh_token', path='/api/auth') is None

    def test_clear_cookies_needs_no_token(self, client):
        response = client.post('/api/auth/clear-cookies', json={})

        assert response.status_code == 200

    def test_clear_cookies_rejects_form_posts(self, client):
        """A cross-site form can send this without a preflight; JSON can't"""
        response = client.post(
            '/api/auth/clear-cookies', data={'x': '1'})

        assert response.status_code == 415
        assert 'Set-Cookie' not in response.headers

    def test_logout_without_cookie(self, client):
        response = client.post('/api/auth/logout')

        assert response.status_code == 401

    def test_logout_all_revokes_every_session(self, client, app, sample_user, fake_redis):
        other_device = app.test_client()
        login(other_device)
        csrf = login(client)
        assert len(fake_redis.tokens) == 2

        response = client.post('/api/auth/logout-all', headers=csrf)

        assert response.status_code == 200
        assert response.get_json()['message'] == 'Logged out from 2 device(s)'
        assert fake_redis.tokens == set()
        cleared = response.headers.getlist('Set-Cookie')
        assert any(c.startswith('__Secure-refresh_token=;') for c in cleared)

    def test_logout_all_leaves_other_users_sessions(self, client, app, sample_user, second_user, fake_redis):
        other_user = app.test_client()
        other_user.post('/api/auth/login', json={
            'email': 'other@example.com', 'password': 'OtherPassword123'})
        csrf = login(client)

        client.post('/api/auth/logout-all', headers=csrf)

        assert [uid for uid, _ in fake_redis.tokens] == [second_user.id]

    def assert_logout_all_failed(self, response):
        """Every session is still live, so this must not look like success,
        and the cookie stays so the user can try again"""
        assert response.status_code == 503
        assert response.get_json()['error']['code'] == 'SERVICE_UNAVAILABLE'
        assert 'Set-Cookie' not in response.headers

    def test_logout_all_when_redis_fails(self, client, sample_user, fake_redis, monkeypatch):
        csrf = login(client)
        monkeypatch.setattr(fake_redis, 'revoke_all_user_tokens', lambda user_id: None)

        self.assert_logout_all_failed(client.post('/api/auth/logout-all', headers=csrf))

    def test_logout_all_when_redis_is_down(self, client, sample_user, fake_redis, monkeypatch):
        csrf = login(client)
        # Only the route loses Redis; the token check still passes
        monkeypatch.setattr(auth_routes, 'get_redis_service', lambda: None)

        self.assert_logout_all_failed(client.post('/api/auth/logout-all', headers=csrf))

    def test_logout_all_while_the_token_store_is_down(
            self, app, client, sample_user, monkeypatch):
        """The token check fails before the route runs; a signed-in user
        must not be told that sign-in is unavailable"""
        csrf = login(client)
        monkeypatch.setitem(app.extensions, 'redis_service', None)

        response = client.post('/api/auth/logout-all', headers=csrf)

        self.assert_logout_all_failed(response)
        assert response.get_json()['error']['message'] == SERVICE_UNAVAILABLE_MESSAGE


class TestAuthenticationFlow:
    """Test complete authentication workflows."""

    def test_register_login_flow(self, client, db):
        """Complete flow: register -> login -> access protected resource."""
        # Register
        register_payload = {
            'email': 'flowtest@example.com',
            'password': 'FlowTest123',
            'terms_version': TERMS_VERSION
        }

        register_response = client.post(
            '/api/auth/register',
            data=json.dumps(register_payload),
            content_type='application/json'
        )
        assert register_response.status_code == 201

        # Login
        login_payload = {
            'email': 'flowtest@example.com',
            'password': 'FlowTest123'
        }

        login_response = client.post(
            '/api/auth/login',
            data=json.dumps(login_payload),
            content_type='application/json'
        )
        assert login_response.status_code == 200

        login_data = json.loads(login_response.data)
        access_token = login_data['access_token']

        # Access protected resource
        headers = {
            'Authorization': f'Bearer {access_token}',
            'Content-Type': 'application/json'
        }

        account_response = client.get('/api/account', headers=headers)
        assert account_response.status_code == 200

    def test_password_typed_either_way_logs_in(self, client, db):
        """é as one character at sign-up, as e plus an accent at login"""
        register = client.post('/api/auth/register', json={
            'email': 'cafe@example.com', 'password': 'CaféPass123', 'terms_version': TERMS_VERSION})
        login = client.post('/api/auth/login', json={
            'email': 'cafe@example.com', 'password': 'CaféPass123'})

        assert register.status_code == 201
        assert login.status_code == 200

    def test_international_domain_is_one_account_however_spelled(self, client, db):
        first = client.post('/api/auth/register', json={
            'email': 'a@bücher.de', 'password': 'ValidPass123', 'terms_version': TERMS_VERSION})
        second = client.post('/api/auth/register', json={
            'email': 'a@xn--bcher-kva.de', 'password': 'ValidPass123', 'terms_version': TERMS_VERSION})

        assert first.status_code == 201
        assert second.status_code == 409

    def test_cannot_register_same_email_twice(self, client):
        """Attempting to register same email twice should fail."""
        payload = {
            'email': 'duplicate@example.com',
            'password': 'ValidPass123',
            'terms_version': TERMS_VERSION
        }

        # First registration
        response1 = client.post(
            '/api/auth/register',
            data=json.dumps(payload),
            content_type='application/json'
        )
        assert response1.status_code == 201

        # Second registration with same email
        response2 = client.post(
            '/api/auth/register',
            data=json.dumps(payload),
            content_type='application/json'
        )
        assert response2.status_code == 409


class TestSignInWithoutRedis:
    """A refresh token Redis never recorded would end the session silently at
    the access token's expiry, so sign-in refuses with 503 instead."""

    def assert_unavailable(self, response):
        assert response.status_code == 503
        assert response.get_json()['error'] == {
            'code': 'SERVICE_UNAVAILABLE', 'message': SERVICE_UNAVAILABLE_MESSAGE}
        assert 'Set-Cookie' not in response.headers

    def test_login_when_redis_is_down(self, app, client, sample_user, no_redis, monkeypatch):
        monkeypatch.setitem(app.config, 'USES_SERVICES', True)
        # Stops get_redis_service() from trying to connect for real
        monkeypatch.setitem(app.extensions, 'redis_retry_at', float('inf'))

        self.assert_unavailable(client.post('/api/auth/login', json=LOGIN_PAYLOAD))

    def test_login_when_redis_rejects_the_write(
            self, client, sample_user, fake_redis, monkeypatch):
        monkeypatch.setattr(fake_redis, 'store_refresh_token', lambda *a, **k: None)

        self.assert_unavailable(client.post('/api/auth/login', json=LOGIN_PAYLOAD))

    def test_refresh_when_redis_rejects_the_write(
            self, client, sample_user, fake_redis, monkeypatch):
        csrf = login(client)
        monkeypatch.setattr(fake_redis, 'rotate_refresh_token', lambda *a, **k: None)

        self.assert_unavailable(client.post('/api/auth/refresh', headers=csrf))


class TestUnusualRefreshTokens:
    """Validly signed refresh tokens the app never issues, and odd conditions
    around them: each must end in a clean 401, or a clean logout"""

    def mint(self, app, **claims):
        """A refresh token signed with the app's key, holding exactly `claims`"""
        now = int(time.time())
        payload = {'type': 'refresh', 'fresh': False, 'csrf': 'csrf',
                   'iat': now, 'nbf': now, 'exp': now + 600, **claims}
        payload = {k: v for k, v in payload.items() if v is not None}
        return jwt.encode(payload, app.config['JWT_SECRET_KEY'], algorithm='HS256')

    def refresh_with(self, client, token):
        client.set_cookie('__Secure-refresh_token', token, path='/api/auth')
        return client.post('/api/auth/refresh', headers={'X-CSRF-REFRESH-TOKEN': 'csrf'})

    @pytest.mark.parametrize('claims, code', [
        # No token id to look up in Redis
        ({'sub': '1', 'jti': None}, 'AUTH_TOKEN_REVOKED'),
        # User ids are integers; Redis cannot vouch for any other
        ({'sub': 'not-a-number', 'jti': 'some-jti'}, 'AUTH_TOKEN_REVOKED'),
        # No user at all: flask-jwt-extended refuses it before the blocklist
        ({'sub': None, 'jti': 'some-jti'}, 'AUTH_INVALID_TOKEN'),
    ])
    def test_is_rejected(self, app, client, sample_user, fake_redis, claims, code):
        response = self.refresh_with(client, self.mint(app, **claims))

        assert response.status_code == 401
        assert response.get_json()['error']['code'] == code

    def test_a_refused_token_logs_its_user_id_as_it_reads(
            self, app, client, sample_user, fake_redis, security_events):
        """Ids are numbers in the log, but a token whose subject is not one
        is still logged rather than crashing the refusal"""
        self.refresh_with(client, self.mint(app, sub='not-a-number', jti='some-jti'))

        assert security_events() == [
            {'message': 'refresh_refused', 'ip': '127.0.0.1', 'user_id': 'not-a-number'}]

    def test_no_csrf_value_is_sent_when_csrf_protection_is_off(
            self, app, client, sample_user, fake_redis, monkeypatch):
        """IntegrationConfig turns it off; a value the server never checks is noise"""
        monkeypatch.setitem(app.config, 'JWT_COOKIE_CSRF_PROTECT', False)

        response = client.post('/api/auth/login', json=LOGIN_PAYLOAD)

        assert response.status_code == 200
        assert 'refresh_csrf' not in response.get_json()

    def test_logout_still_clears_cookies_if_redis_vanishes(
            self, client, sample_user, fake_redis, monkeypatch):
        """Logout is best effort: the token was valid a moment ago, so the
        browser forgets it even though Redis can no longer revoke it"""
        csrf = login(client)
        monkeypatch.setattr(auth_routes, 'get_redis_service', lambda: None)

        response = client.post('/api/auth/logout', headers=csrf)

        assert response.status_code == 200
        assert any(c.startswith('__Secure-refresh_token=;')
                   for c in response.headers.getlist('Set-Cookie'))


class TestSecurityEvents:
    """What an investigation reads: each event names the user and the
    address, and no line carries a password, token, CSRF value or email"""

    def assert_absent(self, logged, *secrets):
        text = json.dumps(logged())
        for secret in secrets:
            assert secret not in text

    def test_register(self, client, db, security_events, logged):
        client.post('/api/auth/register', json={
            'email': 'new@example.com', 'password': 'ValidPass123', 'terms_version': TERMS_VERSION})
        user_id = db.session.scalar(select(User.id).where(User.email == 'new@example.com'))

        assert security_events() == [
            {'message': 'registered', 'ip': '127.0.0.1', 'user_id': user_id}]
        self.assert_absent(logged, 'new@example.com', 'ValidPass123')

    def test_login(self, client, sample_user, fake_redis, security_events, logged):
        body = client.post('/api/auth/login', json=LOGIN_PAYLOAD).get_json()
        cookie = client.get_cookie('__Secure-refresh_token', path='/api/auth').value

        assert security_events() == [
            {'message': 'login_succeeded', 'ip': '127.0.0.1', 'user_id': sample_user.id}]
        self.assert_absent(logged, *LOGIN_PAYLOAD.values(),
                           body['access_token'], body['refresh_csrf'], cookie)

    def test_failed_logins_name_the_account_however_its_email_is_spelled(
            self, client, sample_user, security_events, logged):
        for email in ('test@example.com', 'TEST@Example.com'):
            client.post('/api/auth/login', json={'email': email, 'password': 'WrongPass123'})

        account = auth_routes._email_digest('test@example.com')
        first, second = security_events()
        assert first == {'message': 'login_failed', 'ip': '127.0.0.1',
                         'user_id': sample_user.id, 'account': account}
        # Only MySQL finds the user for the second spelling; SQLite matches
        # case-sensitively. The account is the same either way.
        assert second['account'] == account
        self.assert_absent(logged, 'test@example.com', 'TEST@Example.com', 'WrongPass123')

    def test_a_failed_login_to_an_unknown_email_has_no_user(
            self, client, db, security_events, logged):
        client.post('/api/auth/login', json={
            'email': 'nobody@example.com', 'password': 'WrongPass123'})

        assert security_events() == [
            {'message': 'login_failed', 'ip': '127.0.0.1', 'user_id': None,
             'account': auth_routes._email_digest('nobody@example.com')}]
        self.assert_absent(logged, 'nobody@example.com', 'WrongPass123')

    def test_a_replayed_refresh_token(self, client, sample_user, fake_redis,
                                      security_events, logged):
        csrf = login(client)
        old_cookie = client.get_cookie('__Secure-refresh_token', path='/api/auth').value
        rotated = client.post('/api/auth/refresh', headers=csrf).get_json()

        # A stolen copy of the cookie, used after its owner refreshed
        client.set_cookie('__Secure-refresh_token', old_cookie, path='/api/auth')
        client.post('/api/auth/refresh', headers=csrf)

        assert security_events()[1:] == [
            {'message': 'refresh_refused', 'ip': '127.0.0.1', 'user_id': sample_user.id}]
        self.assert_absent(logged, old_cookie, csrf['X-CSRF-REFRESH-TOKEN'],
                           rotated['access_token'], rotated['refresh_csrf'])

    def test_a_refresh_that_lost_the_rotation_race(
            self, app, client, sample_user, fake_redis, monkeypatch, security_events):
        csrf = login(client)
        cookie = client.get_cookie('__Secure-refresh_token', path='/api/auth').value
        replay = app.test_client(use_cookies=False)
        headers = {**csrf, 'Cookie': f'__Secure-refresh_token={cookie}'}
        monkeypatch.setattr(fake_redis, 'is_token_valid', lambda *args: True)

        replay.post('/api/auth/refresh', headers=headers)
        replay.post('/api/auth/refresh', headers=headers)

        assert security_events()[1:] == [
            {'message': 'refresh_refused', 'ip': '127.0.0.1', 'user_id': sample_user.id}]

    def test_logout(self, client, sample_user, fake_redis, security_events):
        csrf = login(client)

        client.post('/api/auth/logout', headers=csrf)

        assert security_events()[1:] == [
            {'message': 'logout', 'ip': '127.0.0.1', 'user_id': sample_user.id}]

    def test_logout_all(self, app, client, sample_user, fake_redis, security_events):
        login(app.test_client())
        csrf = login(client)

        client.post('/api/auth/logout-all', headers=csrf)

        assert security_events()[2:] == [
            {'message': 'logout_all', 'ip': '127.0.0.1', 'user_id': sample_user.id,
             'sessions': 2}]

    @staticmethod
    def forged(app, user, kind):
        """An access token for `user` that the app never issued"""
        now = int(time.time())
        claims = {'sub': str(user.id), 'type': 'access', 'fresh': False, 'jti': 'j',
                  'iat': now, 'nbf': now, 'exp': now + 600}
        if kind == 'wrong key':
            return jwt.encode(claims, 'k' * 32 + '-not-the-apps', algorithm='HS256')
        if kind == 'alg none':
            return jwt.encode(claims, None, algorithm='none')
        # A refresh token, valid in every way but its type
        with app.app_context():
            return create_refresh_token(identity=str(user.id))

    @pytest.mark.parametrize('kind, reason', [
        ('wrong key', 'Signature verification failed'),
        ('alg none', 'The specified alg value is not allowed'),
        ('refresh as access', 'Only non-refresh tokens are allowed'),
    ])
    def test_a_token_the_app_never_issued(
            self, app, client, sample_user, security_events, logged, kind, reason):
        token = self.forged(app, sample_user, kind)

        response = client.get('/api/account', headers={'Authorization': f'Bearer {token}'})

        assert response.get_json()['error']['code'] == 'AUTH_INVALID_TOKEN'
        assert security_events() == [
            {'message': 'token_invalid', 'ip': '127.0.0.1', 'reason': reason}]
        self.assert_absent(logged, token)

    def test_a_deleted_accounts_token(
            self, client, db, sample_user, auth_headers, security_events, logged):
        user_id = sample_user.id
        db.session.delete(sample_user)
        db.session.commit()

        response = client.get('/api/account', headers=auth_headers)

        assert response.get_json()['error']['code'] == 'AUTH_INVALID_TOKEN'
        assert security_events() == [{'message': 'token_invalid', 'ip': '127.0.0.1',
                                      'reason': 'User not found', 'user_id': user_id}]
        self.assert_absent(logged, auth_headers['Authorization'].removeprefix('Bearer '))

    @pytest.mark.parametrize('headers, reason', [
        ({}, 'Missing CSRF token'),
        ({'X-CSRF-REFRESH-TOKEN': 'guessed'}, 'CSRF double submit tokens do not match'),
    ])
    def test_a_refresh_cookie_without_its_csrf_value(
            self, client, sample_user, fake_redis, security_events, logged, headers, reason):
        csrf = login(client)
        cookie = client.get_cookie('__Secure-refresh_token', path='/api/auth').value

        response = client.post('/api/auth/refresh', headers=headers)

        assert response.status_code == 401
        assert response.get_json()['error']['code'] == 'AUTH_MISSING_TOKEN'
        assert security_events()[1:] == [
            {'message': 'token_invalid', 'ip': '127.0.0.1', 'reason': reason}]
        self.assert_absent(logged, cookie, csrf['X-CSRF-REFRESH-TOKEN'])

    def test_a_request_with_no_token_is_not_an_event(self, client, security_events):
        """A missing Authorization header is a client bug, not an attack"""
        response = client.get('/api/account')

        assert response.get_json()['error']['code'] == 'AUTH_MISSING_TOKEN'
        assert security_events() == []


class TestTokenUserId:
    """The user of a valid token of the given kind, else None: the refresh
    limit's key, checked before @jwt_required runs"""

    def user_id(self, app, token, kind='access'):
        with app.test_request_context():
            return auth_routes.token_user_id(token, kind)

    def test_a_valid_token(self, app, auth_headers, sample_user):
        token = auth_headers['Authorization'].removeprefix('Bearer ')

        assert self.user_id(app, token) == str(sample_user.id)

    @pytest.mark.parametrize('token', [None, '', 'not-a-jwt'])
    def test_no_valid_token(self, app, token):
        assert self.user_id(app, token) is None

    def test_an_expired_token(self, app, expired_token):
        assert self.user_id(app, expired_token) is None

    def test_a_signed_token_without_a_user(self, app):
        """Signed with the app's key, so PyJWT accepts it, but
        flask-jwt-extended refuses a token that names no user"""
        token = jwt.encode(
            {'type': 'access', 'jti': 'x'}, app.config['JWT_SECRET_KEY'], algorithm='HS256')

        assert self.user_id(app, token) is None

    def test_a_token_of_the_other_kind(self, app, sample_user):
        with app.app_context():
            token = create_refresh_token(identity=str(sample_user.id))

        assert self.user_id(app, token) is None
