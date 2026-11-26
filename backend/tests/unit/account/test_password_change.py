"""POST /api/account/password: the current password, then the new one;
every device is logged out, and this one gets a new login"""
import json

import pytest
from flask_jwt_extended import decode_token
from sqlalchemy import update

from app.account import routes as account_routes
from app.auth.models import User
from app.utils.passwords import hash_password

PASSWORD = 'TestPassword123'  # sample_user's
NEW_PASSWORD = 'a brand new passphrase'


@pytest.fixture(autouse=True)
def not_breached(monkeypatch):
    """No third party: a test that needs a breached password says so"""
    monkeypatch.setattr(account_routes, 'is_breached', lambda password: False)


def events(security_events):
    """The events since this device logged in, logins aside"""
    return [event for event in security_events() if event['message'] != 'login_succeeded']


def change(client, headers, current=PASSWORD, new=NEW_PASSWORD):
    return client.post('/api/account/password', headers=headers,
                       json={'current_password': current, 'new_password': new})


def login(client, password):
    return client.post('/api/auth/login', json={'email': 'test@example.com', 'password': password})


@pytest.fixture
def session(client, sample_user, fake_redis):
    """This device's login: its Authorization header"""
    token = login(client, PASSWORD).get_json()['access_token']
    return {'Authorization': f'Bearer {token}'}


def test_sets_the_new_password(client, db, sample_user, session):
    response = change(client, session)

    assert response.status_code == 200
    assert login(client, PASSWORD).status_code == 401
    assert login(client, NEW_PASSWORD).status_code == 200


def test_logs_every_device_out_and_this_one_back_in(client, db, sample_user, session, fake_redis):
    other = login(client, PASSWORD).get_json()['access_token']

    response = change(client, session)

    tokens = response.get_json()
    assert set(tokens) == {'access_token', 'refresh_csrf'}
    # The old tokens were issued under the old password
    assert client.get('/api/account', headers=session).status_code == 401
    assert client.get('/api/account', headers={'Authorization': f'Bearer {other}'}).status_code == 401
    # The new login works, with a refresh token recorded and in the cookie
    assert client.get('/api/account', headers={
        'Authorization': f"Bearer {tokens['access_token']}"}).status_code == 200
    assert fake_redis.tokens == {(sample_user.id, decode_token(
        client.get_cookie('__Secure-refresh_token', path='/api/auth').value)['jti'])}


def test_the_new_login_is_fresh(app, client, db, sample_user, session):
    """The password was just typed: the session's 30 days start again"""
    change(client, session)

    claims = decode_token(client.get_cookie('__Secure-refresh_token', path='/api/auth').value)
    assert claims['auth_time'] == pytest.approx(claims['iat'], abs=2)


def test_emails_the_account(client, db, sample_user, session, jobs):
    change(client, session)

    assert jobs() == [('auth.send_password_changed_email', ('test@example.com', 'change'))]


def test_a_wrong_current_password(client, db, sample_user, session, jobs, security_events):
    response = change(client, session, current='not the password at all')

    assert response.status_code == 403
    assert response.get_json()['error'] == {'code': 'WRONG_PASSWORD', 'message': 'The password is incorrect'}
    assert login(client, PASSWORD).status_code == 200
    assert jobs() == []
    assert events(security_events) == [
        {'message': 'wrong_password', 'ip': '127.0.0.1', 'user_id': sample_user.id}]


def test_the_same_password(client, db, sample_user, session, fake_redis):
    """However it is spelled: NFKC makes full-width letters plain"""
    response = change(client, session, new='ＴｅｓｔＰａｓｓｗｏｒｄ１２３')

    assert response.status_code == 422
    assert response.get_json()['error'] == {
        'code': 'PASSWORD_UNCHANGED', 'message': 'Choose a password different from your current one.'}
    assert len(fake_redis.tokens) == 1


def test_a_guessable_password_never_reaches_the_breach_check(app, client, db, sample_user, session, monkeypatch):
    checked = []
    monkeypatch.setattr(account_routes, 'is_breached', lambda password: checked.append(password) or False)

    response = change(client, session, new=f"I like {app.config['APP_NAME']} a lot")

    assert response.status_code == 422
    assert response.get_json()['error']['code'] == 'PASSWORD_GUESSABLE'
    assert checked == []
    assert login(client, PASSWORD).status_code == 200


def test_a_breached_password(client, db, sample_user, session, monkeypatch):
    monkeypatch.setattr(account_routes, 'is_breached', lambda password: True)

    response = change(client, session)

    assert response.status_code == 422
    assert response.get_json()['error']['code'] == 'PASSWORD_BREACHED'
    assert login(client, PASSWORD).status_code == 200


def test_without_redis_nothing_changes(app, client, db, sample_user, session):
    app.extensions['redis_service'] = None

    response = change(client, session)

    assert response.status_code == 503
    assert response.get_json()['error']['code'] == 'SERVICE_UNAVAILABLE'
    assert db.session.get(User, sample_user.id).check_password(PASSWORD)


def test_of_two_changes_racing_the_second_changes_nothing(client, db, sample_user, session, monkeypatch, jobs):
    """The other change lands between the check and the write"""
    def hash_while_another_change_lands(password):
        db.session.execute(update(User).values(password_hash=hash_password('the other change')))
        db.session.commit()
        return hash_password(password)
    monkeypatch.setattr(account_routes, 'hash_password', hash_while_another_change_lands)

    response = change(client, session)

    assert response.get_json()['error']['code'] == 'WRONG_PASSWORD'
    assert login(client, 'the other change').status_code == 200
    assert jobs() == []


def test_an_email_that_cannot_be_queued_still_logs_in(app, client, db, sample_user, session, logged, queue_down):
    queue_down()

    response = change(client, session)

    assert response.status_code == 200
    assert 'Could not queue the password changed email' in [line['message'] for line in logged()]


@pytest.mark.parametrize('payload', [
    {'current_password': PASSWORD},
    {'new_password': NEW_PASSWORD},
    {'current_password': PASSWORD, 'new_password': 'too short'},
    {'current_password': PASSWORD, 'new_password': NEW_PASSWORD, 'email': 'x@example.com'},
], ids=['no new password', 'no current password', 'a short new one', 'more'])
def test_an_invalid_body(client, db, sample_user, session, payload):
    response = client.post('/api/account/password', headers=session, json=payload)

    assert response.status_code == 422
    assert response.get_json()['error']['code'] == 'VALIDATION_ERROR'


def test_requires_a_session(client, db, sample_user):
    assert change(client, {}).status_code == 401


def test_logs_the_change_without_the_passwords(client, db, sample_user, session, security_events, logged):
    change(client, session)

    assert events(security_events) == [
        {'message': 'password_changed', 'ip': '127.0.0.1', 'user_id': sample_user.id, 'sessions': 1}]
    text = json.dumps(logged())
    assert PASSWORD not in text
    assert NEW_PASSWORD not in text
