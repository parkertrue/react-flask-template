import hashlib
import time
from types import SimpleNamespace

import pytest
import redis
from limits.storage import MemoryStorage
from flask_jwt_extended import (
    create_access_token, create_refresh_token, decode_token, get_csrf_token)
from sqlalchemy import select

from app import db, limiter
from app.auth.models import TERMS_VERSION, User
from app.auth.routes import _login_email_key
from app.utils.passwords import PasswordHashingBusy
from tests.conftest import FakeRedisService
from tests.unit.test_app_factory import build_app

LOGIN = {'email': 'nobody@example.com', 'password': 'WrongPassword123'}


@pytest.fixture
def make_limited_app(monkeypatch):
    """Build apps with the limiter on, behind one trusted proxy like production.

    limiter is module-level and init_app flips its global enabled/initialized
    flags, which would make every other test's app start enforcing limits.
    Snapshot its state and put it back afterwards.
    """
    saved = dict(vars(limiter))

    def make(storage_uri='memory://'):
        app = build_app(
            monkeypatch,
            RATELIMIT_ENABLED=True,
            RATELIMIT_STORAGE_URI=storage_uri,
            TRUSTED_PROXY_COUNT=1,
        )
        with app.app_context():
            db.create_all()
        return app

    yield make
    vars(limiter).clear()
    vars(limiter).update(saved)


@pytest.fixture
def limited_app(make_limited_app):
    return make_limited_app()


def login(client, ip, email=LOGIN['email'], password=LOGIN['password']):
    return client.post(
        '/api/auth/login', json={'email': email, 'password': password},
        headers={'X-Forwarded-For': ip})


@pytest.fixture
def owner_app(limited_app):
    """The limited app with a token store and one real account, owner@example.com"""
    limited_app.extensions['redis_service'] = FakeRedisService()
    with limited_app.app_context():
        user = User(email='owner@example.com')
        user.set_password('TestPassword123')
        db.session.add(user)
        db.session.commit()
    return limited_app


def test_sixth_failed_login_to_one_account_from_one_address_is_rate_limited(limited_app):
    client = limited_app.test_client()

    for _ in range(5):
        assert login(client, '203.0.113.7').status_code == 401

    response = login(client, '203.0.113.7')

    assert response.status_code == 429
    assert response.get_json()['error']['code'] == 'RATE_LIMITED'


def test_a_refusal_is_logged_with_the_limit_and_the_real_client(limited_app, security_events):
    client = limited_app.test_client()
    for _ in range(6):
        login(client, '203.0.113.7')

    assert security_events()[-1] == {
        'message': 'rate_limited', 'ip': '203.0.113.7',
        'path': '/api/auth/login', 'limit': '5 per 1 minute'}


def test_failed_logins_lock_out_only_the_address_sending_them(owner_app):
    """A stranger's wrong guesses must not keep the owner out"""
    client = owner_app.test_client()
    for _ in range(5):
        login(client, '203.0.113.7', 'owner@example.com')
    assert login(client, '203.0.113.7', 'owner@example.com').status_code == 429

    response = login(client, '198.51.100.9', 'owner@example.com', 'TestPassword123')

    assert response.status_code == 200


def test_successful_logins_do_not_count_toward_the_account_limits(owner_app):
    client = owner_app.test_client()

    statuses = [login(client, '203.0.113.7', 'owner@example.com', 'TestPassword123').status_code
                for _ in range(6)]

    assert statuses == [200] * 6


def refuse_hashing(monkeypatch):
    def busy(*args):
        raise PasswordHashingBusy()
    monkeypatch.setattr('app.auth.models.verify_password', busy)


@pytest.mark.parametrize('password, arrange, status', [
    ('Test Password123', lambda monkeypatch: None, 422),  # login refuses spaces
    ('TestPassword123', refuse_hashing, 503),
])
def test_only_wrong_passwords_count_toward_the_account_limits(
        owner_app, monkeypatch, password, arrange, status):
    """An owner retrying through an outage must not lock themselves out"""
    client = owner_app.test_client()
    with monkeypatch.context() as patched:
        arrange(patched)
        statuses = [login(client, '203.0.113.7', 'owner@example.com', password).status_code
                    for _ in range(6)]

    response = login(client, '203.0.113.7', 'owner@example.com', 'TestPassword123')

    assert statuses == [status] * 6
    assert response.status_code == 200


def test_failures_spread_over_many_addresses_hit_the_hourly_account_limit(limited_app, monkeypatch):
    """Guessing one account's password from a botnet stays bounded"""
    # The dummy hash would make 101 logins take seconds; the limit doesn't care
    monkeypatch.setattr('app.auth.routes.verify_password', lambda stored, given: False)
    client = limited_app.test_client()

    statuses = [login(client, f'10.0.{i // 250}.{i % 250}').status_code for i in range(101)]

    assert statuses == [401] * 100 + [429]


def test_account_limit_ignores_email_case(limited_app):
    client = limited_app.test_client()
    for _ in range(5):
        login(client, '203.0.113.7', 'Nobody@Example.com')

    assert login(client, '203.0.113.7', 'nobody@example.com').status_code == 429


def test_account_limit_covers_every_spelling_of_a_domain(limited_app):
    """An international domain and its ASCII form are one account, one bucket"""
    client = limited_app.test_client()
    for _ in range(5):
        login(client, '203.0.113.7', 'nobody@bücher.de')

    assert login(client, '203.0.113.7', 'nobody@xn--bcher-kva.de').status_code == 429


def test_account_limit_keys_reveal_no_address(monkeypatch):
    """Reading Redis must not confirm a guessed address: the key is keyed by
    SECRET_KEY, not a plain hash anyone can recompute."""
    email = 'nobody@example.com'
    keys = []
    for secret in ('a' * 32, 'b' * 32):
        app = build_app(monkeypatch, JWT_SECRET_KEY=secret)
        with app.test_request_context(json={'email': email}):
            keys.append(_login_email_key())

    assert keys[0] != keys[1]
    plain_hash = hashlib.sha256(email.encode()).hexdigest()
    for key in keys:
        assert email not in key
        assert plain_hash not in key


@pytest.mark.parametrize('body', [{'email': 123, 'password': 'x'}, ['not', 'an', 'object']])
def test_a_malformed_login_is_a_validation_error_not_a_crash(limited_app, body):
    """The per-account limit reads the email before the schema has checked it"""
    response = limited_app.test_client().post('/api/auth/login', json=body)

    assert response.status_code == 422


def test_one_address_can_log_in_to_many_accounts_without_limiting_others(
        limited_app, monkeypatch):
    """An office behind one NAT gets 20 logins a minute, not 5, and its
    bucket is its own"""
    # The limiter is under test, not the dummy hash every unknown email costs
    monkeypatch.setattr('app.auth.routes.verify_password', lambda *args: False)
    client = limited_app.test_client()

    statuses = [login(client, '203.0.113.7', f'user{i}@example.com').status_code
                for i in range(21)]

    assert statuses == [401] * 20 + [429]
    assert login(client, '198.51.100.9', 'other@example.com').status_code == 401


def register(client, ip):
    # One email throughout: after the first, each is a fast 409 that still counts
    return client.post(
        '/api/auth/register',
        json={'email': 'new@example.com', 'password': 'TestPassword123', 'terms_version': TERMS_VERSION},
        headers={'X-Forwarded-For': ip})


def test_eleventh_registration_from_one_address_in_an_hour_is_rate_limited(limited_app):
    client = limited_app.test_client()

    statuses = [register(client, '203.0.113.7').status_code for _ in range(11)]

    assert statuses == [201] + [409] * 9 + [429]


def test_registration_limit_is_per_address(limited_app):
    client = limited_app.test_client()
    for _ in range(11):
        register(client, '203.0.113.7')

    assert register(client, '198.51.100.9').status_code == 409


class TestRefreshLimit:
    """Refresh is limited per user, so a shared address never trips it"""

    @pytest.fixture
    def refresh_app(self, limited_app):
        limited_app.extensions['redis_service'] = FakeRedisService()
        return limited_app

    def refresh_headers(self, app, email):
        """Cookie and CSRF headers for a fresh, recorded refresh token"""
        with app.app_context():
            user = User(email=email)
            user.set_password('TestPassword123')
            db.session.add(user)
            db.session.commit()
            token = create_refresh_token(
                identity=str(user.id), additional_claims={'auth_time': int(time.time())})
            app.extensions['redis_service'].store_refresh_token(
                user.id, decode_token(token)['jti'], ttl_seconds=60)
            return {
                'Cookie': f'__Secure-refresh_token={token}',
                'X-CSRF-REFRESH-TOKEN': get_csrf_token(token),
            }

    def refresh(self, client, headers, ip):
        return client.post(
            '/api/auth/refresh', headers={**headers, 'X-Forwarded-For': ip})

    def test_eleventh_refresh_by_one_user_is_rate_limited(self, refresh_app):
        # No cookie jar: every request replays the first token. After it
        # rotates, the replays are revoked (401) but still count.
        client = refresh_app.test_client(use_cookies=False)
        headers = self.refresh_headers(refresh_app, 'a@example.com')

        statuses = [self.refresh(client, headers, f'203.0.113.{i}').status_code
                    for i in range(11)]

        assert statuses == [200] + [401] * 9 + [429]

    def test_users_sharing_an_address_have_their_own_buckets(self, refresh_app):
        client = refresh_app.test_client(use_cookies=False)
        first = self.refresh_headers(refresh_app, 'a@example.com')
        for _ in range(11):
            self.refresh(client, first, '203.0.113.7')

        second = self.refresh_headers(refresh_app, 'b@example.com')

        assert self.refresh(client, second, '203.0.113.7').status_code == 200

    @pytest.mark.parametrize('headers', [
        {'Cookie': '__Secure-refresh_token=not-a-jwt'},
        {},
    ], ids=['forged', 'missing'])
    def test_requests_without_a_valid_cookie_are_not_limited(self, refresh_app, headers):
        """They get a 401, which tells the client to sign in again"""
        client = refresh_app.test_client(use_cookies=False)

        statuses = {self.refresh(client, headers, '203.0.113.7').status_code
                    for _ in range(15)}

        assert statuses == {401}

    def test_an_access_token_in_the_cookie_is_not_limited(self, refresh_app):
        """Validly signed but the wrong type: as good as no cookie"""
        client = refresh_app.test_client(use_cookies=False)
        with refresh_app.app_context():
            access = {'Cookie': f'__Secure-refresh_token={create_access_token(identity="1")}'}

        statuses = {self.refresh(client, access, '203.0.113.7').status_code
                    for _ in range(15)}

        assert statuses == {401}


class TestDeleteAccountLimit:
    """Deleting an account asks for the password, so it is limited like a
    login: per user, counting wrong passwords only, and hourly per account in
    the same budget as login's"""

    @pytest.fixture
    def clock(self, monkeypatch):
        """The limiter's clock, moved by hand, so requests can be spread over
        an hour without waiting. Tokens keep the real clock."""
        now = [time.time()]
        monkeypatch.setattr('limits.storage.memory.time', SimpleNamespace(time=lambda: now[0]))
        return now

    @pytest.fixture
    def fast_hashing(self, monkeypatch):
        """Every password is wrong, at once; the limits don't care how long a
        hash takes"""
        monkeypatch.setattr('app.auth.models.verify_password', lambda stored, given: False)
        monkeypatch.setattr('app.auth.routes.verify_password', lambda stored, given: False)

    def headers(self, app, email, ip='203.0.113.7'):
        with app.app_context():
            user_id = db.session.scalar(select(User.id).where(User.email == email))
            token = create_access_token(identity=str(user_id))
        return {'Authorization': f'Bearer {token}', 'X-Forwarded-For': ip}

    def delete(self, client, headers, password='WrongPassword123'):
        return client.post('/api/account/delete', headers=headers, json={'password': password})

    def test_sixth_wrong_password_in_a_minute_is_rate_limited(self, owner_app):
        client = owner_app.test_client()
        headers = self.headers(owner_app, 'owner@example.com')

        statuses = [self.delete(client, headers).status_code for _ in range(6)]

        assert statuses == [403] * 5 + [429]

    def test_the_limit_follows_the_user_across_addresses(self, owner_app):
        client = owner_app.test_client()
        statuses = [
            self.delete(client, self.headers(owner_app, 'owner@example.com', f'203.0.113.{i}'))
            .status_code for i in range(6)]

        assert statuses == [403] * 5 + [429]

    def test_users_sharing_an_address_have_their_own_buckets(self, owner_app):
        with owner_app.app_context():
            other = User(email='other@example.com')
            other.set_password('OtherPassword123')
            db.session.add(other)
            db.session.commit()
        client = owner_app.test_client()
        for _ in range(6):
            self.delete(client, self.headers(owner_app, 'owner@example.com'))

        response = self.delete(
            client, self.headers(owner_app, 'other@example.com'), 'OtherPassword123')

        assert response.status_code == 200

    def test_requests_without_a_valid_token_are_not_limited(self, owner_app):
        """@jwt_required turns them away cheaply"""
        client = owner_app.test_client()

        statuses = {self.delete(client, {'Authorization': 'Bearer not-a-jwt'}).status_code
                    for _ in range(10)}

        assert statuses == {401}

    @pytest.mark.usefixtures('fast_hashing')
    def test_wrong_passwords_spread_over_an_hour_hit_the_account_limit(self, owner_app, clock):
        """Four a minute stays under the per-minute limit, not the hourly one"""
        client = owner_app.test_client()
        headers = self.headers(owner_app, 'owner@example.com')
        statuses = []
        for _ in range(101):
            statuses.append(self.delete(client, headers).status_code)
            clock[0] += 15

        assert statuses == [403] * 100 + [429]

    @pytest.mark.usefixtures('fast_hashing')
    def test_login_and_deletion_share_the_account_budget(self, owner_app, clock):
        """Guessing behind a session adds to guessing at the login form"""
        client = owner_app.test_client()
        headers = self.headers(owner_app, 'owner@example.com')
        statuses = []
        for i in range(50):
            statuses.append(self.delete(client, headers).status_code)
            statuses.append(login(client, f'10.0.0.{i}', email='owner@example.com').status_code)
            clock[0] += 15

        assert statuses == [403, 401] * 50
        assert self.delete(client, headers).status_code == 429
        assert login(client, '10.0.1.1', email='owner@example.com').status_code == 429


def test_unlimited_routes_have_no_per_ip_quota(limited_app):
    """Only routes that declare a limit have one.

    A default quota would fail the container healthcheck, which polls every
    10s from one address, and lock out every user behind a shared NAT.
    """
    client = limited_app.test_client()

    statuses = {client.get('/api/health').status_code for _ in range(250)}

    assert statuses == {200}


def test_limits_fall_back_to_memory_when_redis_is_down(make_limited_app, monkeypatch):
    """An unreachable limiter store must not turn every request into a 500"""
    # Refuse every connection at once. A real closed port behaves the same,
    # but Windows takes ~2s to report each refusal.
    def refuse(self):
        raise redis.ConnectionError('Connection refused')
    monkeypatch.setattr(redis.connection.Connection, '_connect', refuse)

    client = make_limited_app('redis://127.0.0.1:1').test_client()

    statuses = [login(client, '203.0.113.7').status_code for _ in range(6)]

    assert statuses == [401] * 5 + [429]  # the account-and-address limit, now in memory


def test_a_failed_login_that_cannot_be_counted_still_answers_401(limited_app, monkeypatch):
    """A full Redis still answers reads, so the limit check passes; only
    counting the failure, after the response is built, is refused"""
    incr = MemoryStorage.incr

    def refuse_account_counts(self, key, *args, **kwargs):
        if 'email:' in key:
            raise redis.OutOfMemoryError("command not allowed when used memory > 'maxmemory'")
        return incr(self, key, *args, **kwargs)
    monkeypatch.setattr(MemoryStorage, 'incr', refuse_account_counts)

    response = login(limited_app.test_client(), '203.0.113.7')

    assert response.status_code == 401


def test_limiter_state_is_restored(app, client):
    """The shared unit app must not inherit limits from the tests above"""
    for _ in range(6):
        response = client.post('/api/auth/login', json=LOGIN)

    assert response.status_code == 401
