import json
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select

from app.auth.models import User
from app.utils.exports import registered_exports
from tests.conftest import register


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


class TestExportAccount:
    """GET /api/account/export: the account, plus each feature's rows (tests
    of a feature's own rows live in its folder)"""

    def test_returns_the_account_without_its_password_hash(
            self, client, sample_user, auth_headers):
        response = client.get('/api/account/export', headers=auth_headers)

        assert response.status_code == 200
        assert response.get_json()['account'] == {
            'email': sample_user.email,
            'created_at': sample_user.created_at.isoformat() + '+00:00',
            'terms_version': sample_user.terms_version,
            'terms_accepted_at': sample_user.terms_accepted_at.isoformat() + '+00:00',
        }
        assert sample_user.password_hash not in response.get_data(as_text=True)

    def test_holds_every_registered_feature_empty_for_a_new_user(
            self, app, client, sample_user, auth_headers):
        response = client.get('/api/account/export', headers=auth_headers)

        body = response.get_json()
        assert set(body) == {'exported_at', 'account', 'data'}
        with app.app_context():
            assert body['data'] == {name: [] for name in registered_exports()}

    def test_states_when_it_was_made_in_utc(self, client, sample_user, auth_headers):
        before = datetime.now(timezone.utc)

        response = client.get('/api/account/export', headers=auth_headers)

        exported_at = datetime.fromisoformat(response.get_json()['exported_at'])
        assert exported_at.utcoffset() == timedelta(0)
        assert before <= exported_at <= datetime.now(timezone.utc)

    def test_another_users_token_gets_their_own_account(
            self, client, sample_user, second_user, second_auth_headers):
        response = client.get('/api/account/export', headers=second_auth_headers)

        assert response.get_json()['account']['email'] == second_user.email

    def test_requires_a_token(self, client):
        response = client.get('/api/account/export')

        assert response.status_code == 401
        assert response.get_json()['error']['code'] == 'AUTH_MISSING_TOKEN'

    def test_is_a_security_event(self, client, sample_user, auth_headers, security_events, logged):
        user_id, email = sample_user.id, sample_user.email

        client.get('/api/account/export', headers=auth_headers)

        assert security_events() == [
            {'message': 'data_exported', 'ip': '127.0.0.1', 'user_id': user_id}]
        assert email not in json.dumps(logged())


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
        assert [c.split(';')[0] for c in cleared] == ['__Secure-refresh_token=']

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

        response = register(client, email, PASSWORD, terms_version)

        assert response.status_code == 200

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
        # The rules registration applies: no password it refuses is checked
        {'password': 'short password'},
        {'password': 'a tab\tin a long password'},
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

