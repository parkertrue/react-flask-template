import json
from datetime import datetime, timedelta

import pytest
from flask_jwt_extended import create_refresh_token
from sqlalchemy import select

from app.account import routes as account_routes
from app.auth.models import User


def test_returns_the_signed_in_users_account(client, sample_user, auth_headers):
    response = client.get('/api/account', headers=auth_headers)

    assert response.status_code == 200
    body = response.get_json()
    assert set(body) == {'email', 'created_at'}
    assert body['email'] == sample_user.email


def test_created_at_is_sent_as_utc(client, sample_user, auth_headers):
    """The database's naive DATETIME goes out with its zone stated"""
    response = client.get('/api/account', headers=auth_headers)

    created_at = datetime.fromisoformat(response.get_json()['created_at'])
    assert created_at.utcoffset() == timedelta(0)
    assert created_at.replace(tzinfo=None) == sample_user.created_at


def test_another_users_token_gets_their_own_account(
        client, second_user, second_auth_headers):
    response = client.get('/api/account', headers=second_auth_headers)

    assert response.get_json()['email'] == second_user.email


def test_requires_a_token(client):
    response = client.get('/api/account')

    assert response.status_code == 401
    assert response.get_json()['error']['code'] == 'AUTH_MISSING_TOKEN'


PASSWORD = 'TestPassword123'  # sample_user's


def delete_account(client, headers, password=PASSWORD):
    return client.post('/api/account/delete', headers=headers, json={'password': password})


def user_exists(db, user_id):
    return db.session.scalar(select(User.id).where(User.id == user_id)) == user_id


class TestDeleteAccount:
    """POST /api/account/delete"""

    def test_deletes_the_user(self, client, db, sample_user, auth_headers):
        user_id = sample_user.id

        response = delete_account(client, auth_headers)

        assert response.status_code == 200
        assert response.get_json() == {'message': 'Account deleted'}
        assert not user_exists(db, user_id)

    def test_only_deletes_the_tokens_owner(
            self, client, db, sample_user, second_user, second_auth_headers):
        response = delete_account(client, second_auth_headers, password='OtherPassword123')

        assert response.status_code == 200
        assert user_exists(db, sample_user.id)
        assert not user_exists(db, second_user.id)

    def test_ends_every_session_and_clears_the_cookie(
            self, app, client, sample_user, second_user, auth_headers, fake_redis):
        for email, password in [(sample_user.email, PASSWORD),
                                (sample_user.email, PASSWORD),
                                (second_user.email, 'OtherPassword123')]:
            app.test_client().post('/api/auth/login', json={'email': email, 'password': password})

        response = delete_account(client, auth_headers)

        assert [uid for uid, _ in fake_redis.tokens] == [second_user.id]
        cleared = response.headers.getlist('Set-Cookie')
        assert any(c.startswith('__Secure-refresh_token=;') for c in cleared)

    def test_a_refresh_after_deleting_is_refused(self, client, sample_user, auth_headers):
        login = client.post('/api/auth/login', json={'email': sample_user.email, 'password': PASSWORD})
        cookie = client.get_cookie('__Secure-refresh_token', path='/api/auth').value
        delete_account(client, auth_headers)

        # Replay the session's cookie, as a stolen one would be
        client.set_cookie('__Secure-refresh_token', cookie, path='/api/auth')
        response = client.post('/api/auth/refresh', headers={
            'X-CSRF-REFRESH-TOKEN': login.get_json()['refresh_csrf']})

        assert response.status_code == 401
        assert response.get_json()['error']['code'] == 'AUTH_TOKEN_REVOKED'

    def test_the_access_token_stops_working(self, client, sample_user, auth_headers):
        delete_account(client, auth_headers)

        response = client.get('/api/account', headers=auth_headers)

        assert response.status_code == 401
        assert response.get_json()['error']['code'] == 'AUTH_INVALID_TOKEN'

    def test_the_email_can_register_again(self, client, sample_user, auth_headers):
        email, terms_version = sample_user.email, sample_user.terms_version
        delete_account(client, auth_headers)

        response = client.post('/api/auth/register', json={
            'email': email, 'password': PASSWORD, 'terms_version': terms_version})

        assert response.status_code == 201

    def test_a_wrong_password_deletes_nothing(self, client, db, sample_user, auth_headers):
        """403, not 401: the client takes a 401 for a session that has ended"""
        response = delete_account(client, auth_headers, password='WrongPassword123')

        assert response.status_code == 403
        assert response.get_json()['error'] == {
            'code': 'WRONG_PASSWORD', 'message': 'The password is incorrect'}
        assert user_exists(db, sample_user.id)
        assert 'Set-Cookie' not in response.headers

    def test_the_password_is_normalized_as_at_login(self, client, db, sample_user, auth_headers):
        """Full-width letters are NFKC-normalized to the plain ones hashed"""
        full_width = ''.join(chr(ord(c) + 0xFEE0) for c in PASSWORD)

        response = delete_account(client, auth_headers, password=full_width)

        assert response.status_code == 200
        assert not user_exists(db, sample_user.id)

    @pytest.mark.parametrize('body', [
        {},
        {'password': ''},
        {'password': 'Test Password123'},
        # The rules registration applies: no password it refuses is checked
        {'password': 'Pass123'},
        {'password': 'testpassword123'},
        {'password': 'TESTPASSWORD123'},
        {'password': 'TestPassword'},
        {'password': 123},
        {'password': PASSWORD, 'extra': 1},
    ])
    def test_a_malformed_body_is_a_validation_error(
            self, client, db, sample_user, auth_headers, body):
        response = client.post('/api/account/delete', headers=auth_headers, data=json.dumps(body))

        assert response.status_code == 422
        assert response.get_json()['error']['code'] == 'VALIDATION_ERROR'
        assert user_exists(db, sample_user.id)

    def test_requires_a_token(self, client, db, sample_user):
        response = client.post('/api/account/delete', json={'password': PASSWORD})

        assert response.status_code == 401
        assert response.get_json()['error']['code'] == 'AUTH_MISSING_TOKEN'
        assert user_exists(db, sample_user.id)

    def assert_nothing_deleted(self, db, user_id, response):
        """The sessions are all still live, so nothing may be deleted yet:
        the user can try again"""
        assert response.status_code == 503
        assert response.get_json()['error'] == {
            'code': 'SERVICE_UNAVAILABLE',
            'message': 'Could not delete the account, please try again shortly'}
        assert user_exists(db, user_id)
        assert 'Set-Cookie' not in response.headers

    def test_nothing_is_deleted_when_redis_fails(
            self, client, db, sample_user, auth_headers, fake_redis, monkeypatch):
        monkeypatch.setattr(fake_redis, 'revoke_all_user_tokens', lambda user_id: None)

        self.assert_nothing_deleted(db, sample_user.id, delete_account(client, auth_headers))

    @pytest.mark.usefixtures('no_redis')
    def test_nothing_is_deleted_when_redis_is_down(self, client, db, sample_user, auth_headers):
        self.assert_nothing_deleted(db, sample_user.id, delete_account(client, auth_headers))

    def test_is_a_security_event(self, client, sample_user, auth_headers, security_events, logged):
        user_id, email = sample_user.id, sample_user.email

        delete_account(client, auth_headers)

        assert security_events() == [
            {'message': 'account_deleted', 'ip': '127.0.0.1', 'user_id': user_id}]
        text = json.dumps(logged())
        for secret in (PASSWORD, email, auth_headers['Authorization'].removeprefix('Bearer ')):
            assert secret not in text

    def test_a_wrong_password_is_a_security_event(
            self, client, sample_user, auth_headers, security_events, logged):
        """Guessing behind a stolen session shows in the log"""
        user_id, email = sample_user.id, sample_user.email

        delete_account(client, auth_headers, password='WrongPassword123')

        assert security_events() == [
            {'message': 'wrong_password', 'ip': '127.0.0.1', 'user_id': user_id}]
        text = json.dumps(logged())
        for secret in ('WrongPassword123', email):
            assert secret not in text


class TestAccessUserId:
    """The delete limit's key: the user of a valid access token, else None"""

    def user_id(self, app, headers):
        with app.test_request_context(headers=headers):
            return account_routes._access_user_id()

    def test_a_valid_access_token(self, app, sample_user, auth_headers):
        assert self.user_id(app, auth_headers) == str(sample_user.id)

    @pytest.mark.parametrize('headers', [
        {},
        {'Authorization': 'Basic abc'},
        {'Authorization': 'Bearer not-a-jwt'},
    ])
    def test_no_valid_token(self, app, headers):
        assert self.user_id(app, headers) is None

    def test_an_expired_token(self, app, expired_token):
        assert self.user_id(app, {'Authorization': f'Bearer {expired_token}'}) is None

    def test_a_refresh_token(self, app, sample_user):
        with app.app_context():
            token = create_refresh_token(identity=str(sample_user.id))

        assert self.user_id(app, {'Authorization': f'Bearer {token}'}) is None
