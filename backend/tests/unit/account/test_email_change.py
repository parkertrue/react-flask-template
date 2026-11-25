"""An email change: the request (signed in, with the password), the link to
the new address that moves the account, and the link to the old one that
moves it back"""
import json
import time
from datetime import timedelta
from unittest.mock import patch

import pytest
from dramatiq import Message
from itsdangerous import TimestampSigner
from redis import ConnectionError as RedisConnectionError
from sqlalchemy import select

from app import db as _db
from app.account import routes as account_routes
from app.account.emails import (
    EMAIL_CHANGE_LINK, EMAIL_CHANGE_LINK_LIFETIME, EMAIL_UNDO_LINK, EMAIL_UNDO_LINK_LIFETIME,
    change_state, undo_state)
from app.auth.emails import REGISTRATION_LINK
from app.auth.models import User
from app.utils.jobs import QUEUE_NAME
from app.utils.links import make_link_token

PASSWORD = 'TestPassword123'  # sample_user's
NEW_EMAIL = 'new@example.com'


def change_token(app, user, email=NEW_EMAIL, ago=timedelta(0)):
    """The link the worker would email the new address, as if sent `ago` before now"""
    then = int(time.time() - ago.total_seconds())
    with app.app_context(), patch.object(TimestampSigner, 'get_timestamp', return_value=then):
        return make_link_token(EMAIL_CHANGE_LINK, email, change_state(db_user(user)))


def undo_token(app, user, email='test@example.com', ago=timedelta(0)):
    """The link the worker would email the old address once it is changed"""
    then = int(time.time() - ago.total_seconds())
    with app.app_context(), patch.object(TimestampSigner, 'get_timestamp', return_value=then):
        return make_link_token(EMAIL_UNDO_LINK, email, undo_state(db_user(user)))


def db_user(user):
    """user as the current app context's session has it"""
    return _db.session.get(User, user.id)


def current_email(db, user):
    return db.session.scalar(select(User.email).where(User.id == user.id))


@pytest.fixture
def owner_takes_back(app, monkeypatch):
    """The owner changes the password, as the password-changed email advises"""
    monkeypatch.setitem(app.config, 'APP_URL', 'https://app.test')
    monkeypatch.setattr(account_routes, 'is_breached', lambda password: False)

    def change(client, headers):
        response = client.post('/api/account/password', headers=headers, json={
            'current_password': PASSWORD, 'new_password': 'An entirely new passphrase'})
        assert response.status_code == 200
    return change


class TestRequestEmailChange:
    """POST /api/account/email"""

    def request_change(self, client, headers, email=NEW_EMAIL, password=PASSWORD):
        return client.post('/api/account/email', headers=headers, json={'email': email, 'password': password})

    @pytest.mark.parametrize('email', [NEW_EMAIL, 'other@example.com'],
                             ids=['a free address', "another account's"])
    def test_queues_the_link_and_answers_alike(self, client, db, sample_user, second_user, auth_headers, jobs,
                                               email):
        response = self.request_change(client, auth_headers, email)

        assert response.status_code == 202
        assert response.get_json() == {'message': 'Check your inbox'}
        assert jobs() == [('account.send_email_change_email', (sample_user.id, email, change_state(sample_user)))]

    def test_changes_nothing_yet(self, client, db, sample_user, auth_headers, jobs):
        self.request_change(client, auth_headers)

        assert current_email(db, sample_user) == 'test@example.com'

    def test_queues_the_address_as_it_is_stored(self, client, db, sample_user, auth_headers, jobs):
        self.request_change(client, auth_headers, 'A@bücher.DE')

        assert jobs() == [
            ('account.send_email_change_email', (sample_user.id, 'A@xn--bcher-kva.de', change_state(sample_user)))]

    def test_a_wrong_password(self, client, db, sample_user, auth_headers, jobs, security_events):
        response = self.request_change(client, auth_headers, password='not the password at all')

        assert response.status_code == 403
        assert response.get_json()['error'] == {
            'code': 'WRONG_PASSWORD', 'message': 'The password is incorrect'}
        assert jobs() == []
        assert security_events() == [
            {'message': 'wrong_password', 'ip': '127.0.0.1', 'user_id': sample_user.id}]

    def test_the_current_address(self, client, db, sample_user, auth_headers, jobs):
        """However it is spelled"""
        response = self.request_change(client, auth_headers, 'TEST@example.com')

        assert response.status_code == 422
        assert response.get_json()['error'] == {
            'code': 'EMAIL_UNCHANGED', 'message': 'This is already your email address'}
        assert jobs() == []

    @pytest.mark.parametrize('payload', [
        {'email': 'not-an-email', 'password': PASSWORD},
        {'password': PASSWORD},
        {'email': NEW_EMAIL},
        {'email': NEW_EMAIL, 'password': PASSWORD, 'user_id': 2},
    ], ids=['a bad address', 'no address', 'no password', 'more'])
    def test_an_invalid_body(self, client, db, sample_user, auth_headers, jobs, payload):
        response = client.post('/api/account/email', headers=auth_headers, json=payload)

        assert response.status_code == 422
        assert response.get_json()['error']['code'] == 'VALIDATION_ERROR'
        assert jobs() == []

    def test_a_password_change_before_the_job_runs_ends_the_change(
            self, app, client, db, sample_user, auth_headers, jobs, outbox, run_jobs, owner_takes_back):
        """An intruder asks while the queue is backed up; the owner changes the
        password first: the new address gets nothing"""
        self.request_change(client, auth_headers)
        owner_takes_back(client, auth_headers)

        run_jobs()

        # Only the owner's notice of the password change
        assert [message['To'] for message in outbox] == ['test@example.com']

    def test_a_replayed_request_sends_nothing_after_a_password_change(
            self, app, client, db, sample_user, auth_headers, jobs, outbox, run_jobs, owner_takes_back):
        """The message is signed, but a replay of it must not mint a link
        that works under the new password"""
        broker = app.extensions['jobs_broker']
        self.request_change(client, auth_headers)
        [asked] = [Message.decode(message) for message in broker.queues[QUEUE_NAME].queue]
        run_jobs()
        owner_takes_back(client, auth_headers)
        run_jobs()

        broker.enqueue(asked)
        run_jobs()

        assert [message['To'] for message in outbox] == [NEW_EMAIL, 'test@example.com']

    def test_requires_a_session(self, client, db, sample_user, jobs):
        response = client.post('/api/account/email', json={'email': NEW_EMAIL, 'password': PASSWORD})

        assert response.status_code == 401
        assert jobs() == []

    def test_a_queue_that_is_down_is_a_503(self, app, client, db, sample_user, auth_headers, monkeypatch):
        def refuse(message, *, delay=None):
            raise RedisConnectionError('Connection refused')
        monkeypatch.setattr(app.extensions['jobs_broker'], 'enqueue', refuse)

        response = self.request_change(client, auth_headers)

        assert response.status_code == 503
        assert response.get_json()['error']['code'] == 'SERVICE_UNAVAILABLE'

    def test_logs_the_request_without_the_addresses(
            self, client, db, sample_user, auth_headers, jobs, security_events, logged):
        self.request_change(client, auth_headers)

        assert security_events() == [
            {'message': 'email_change_requested', 'ip': '127.0.0.1', 'user_id': sample_user.id}]
        text = json.dumps(logged())
        assert NEW_EMAIL not in text
        assert 'test@example.com' not in text


class TestCompleteEmailChange:
    """POST /api/account/email/complete: the link to the new address"""

    def complete(self, client, token):
        return client.post('/api/account/email/complete', json={'token': token})

    def test_moves_the_account(self, app, client, db, sample_user, jobs):
        response = self.complete(client, change_token(app, sample_user))

        assert response.status_code == 200
        assert response.get_json() == {'email': NEW_EMAIL}
        assert current_email(db, sample_user) == NEW_EMAIL

    def test_tells_the_old_address(self, app, client, db, sample_user, jobs):
        self.complete(client, change_token(app, sample_user))

        assert jobs() == [('account.send_email_changed_email', (sample_user.id, 'test@example.com'))]

    def test_keeps_the_account_s_sessions_and_needs_none(
            self, app, client, db, sample_user, auth_headers, jobs):
        """Tokens name the account by id; the link may be opened anywhere"""
        self.complete(client, change_token(app, sample_user))

        account = client.get('/api/account', headers=auth_headers)
        assert account.get_json()['email'] == NEW_EMAIL

    def test_a_link_works_once(self, app, client, db, sample_user, jobs):
        token = change_token(app, sample_user)
        self.complete(client, token)

        response = self.complete(client, token)

        assert response.status_code == 400
        assert response.get_json()['error'] == {
            'code': 'LINK_USED', 'message': 'This link has already been used'}

    def test_a_password_change_ends_the_link(self, app, client, db, sample_user, jobs):
        """An owner who resets the password cancels a change an intruder asked for"""
        token = change_token(app, sample_user)
        sample_user.set_password('a changed passphrase')
        db.session.commit()

        response = self.complete(client, token)

        assert response.get_json()['error']['code'] == 'LINK_USED'
        assert current_email(db, sample_user) == 'test@example.com'

    def test_an_address_taken_since_the_link_was_sent(self, app, client, db, sample_user, jobs):
        token = change_token(app, sample_user, 'other@example.com')
        taken = User(email='other@example.com')
        taken.set_password('OtherPassword123')
        db.session.add(taken)
        db.session.commit()

        response = self.complete(client, token)

        assert response.status_code == 409
        assert response.get_json()['error']['code'] == 'EMAIL_ALREADY_REGISTERED'
        assert current_email(db, sample_user) == 'test@example.com'
        assert jobs() == []

    def test_an_address_taken_between_the_check_and_the_write(
            self, app, client, db, sample_user, jobs, monkeypatch):
        """The unique index is the real check"""
        monkeypatch.setattr(account_routes, 'select', lambda *a: select(User.id).where(User.id == -1))
        token = change_token(app, sample_user, 'other@example.com')
        taken = User(email='other@example.com')
        taken.set_password('OtherPassword123')
        db.session.add(taken)
        db.session.commit()

        response = self.complete(client, token)

        assert response.status_code == 409
        assert current_email(db, sample_user) == 'test@example.com'

    def test_an_expired_link(self, app, client, db, sample_user, jobs):
        token = change_token(app, sample_user, ago=EMAIL_CHANGE_LINK_LIFETIME + timedelta(seconds=5))

        response = self.complete(client, token)

        assert response.status_code == 400
        assert response.get_json()['error']['code'] == 'LINK_EXPIRED'

    def test_a_link_just_before_it_expires(self, app, client, db, sample_user, jobs):
        token = change_token(app, sample_user, ago=EMAIL_CHANGE_LINK_LIFETIME - timedelta(seconds=5))

        assert self.complete(client, token).status_code == 200

    @pytest.mark.parametrize(('state', 'code'), [
        ('', 'LINK_INVALID'), ('x:y', 'LINK_INVALID'), ('999:y', 'LINK_INVALID'), ('1:wrong', 'LINK_USED'),
    ], ids=['empty', 'no id', 'no such account', 'another hash'])
    def test_a_state_naming_no_account_or_another(self, app, client, db, sample_user, jobs, state, code):
        """Signed by this app, so only a bug could mint one; an id of the
        right account with another hash is a link that has been used"""
        with app.app_context():
            token = make_link_token(EMAIL_CHANGE_LINK, NEW_EMAIL, state.replace('1:', f'{sample_user.id}:'))

        response = self.complete(client, token)

        assert response.get_json()['error']['code'] == code
        assert current_email(db, sample_user) == 'test@example.com'

    def test_another_purpose_s_link(self, app, client, db, sample_user, jobs):
        with app.app_context():
            token = make_link_token(REGISTRATION_LINK, NEW_EMAIL, change_state(db_user(sample_user)))

        assert self.complete(client, token).get_json()['error']['code'] == 'LINK_INVALID'

    def test_a_notice_that_cannot_be_queued_still_answers_changed(
            self, app, client, db, sample_user, monkeypatch, logged):
        def refuse(message, *, delay=None):
            raise RedisConnectionError('Connection refused')
        monkeypatch.setattr(app.extensions['jobs_broker'], 'enqueue', refuse)

        response = self.complete(client, change_token(app, sample_user))

        assert response.status_code == 200
        assert 'Could not queue the email changed email' in [line['message'] for line in logged()]

    def test_logs_the_change_without_the_addresses(
            self, app, client, db, sample_user, jobs, security_events, logged):
        token = change_token(app, sample_user)

        self.complete(client, token)

        assert security_events() == [
            {'message': 'email_changed', 'ip': '127.0.0.1', 'user_id': sample_user.id}]
        text = json.dumps(logged())
        assert NEW_EMAIL not in text
        assert token not in text


class TestUndoEmailChange:
    """POST /api/account/email/undo: the link to the old address"""

    @pytest.fixture
    def moved(self, app, client, db, sample_user, jobs):
        """sample_user's account, moved to NEW_EMAIL"""
        client.post('/api/account/email/complete', json={'token': change_token(app, sample_user)})
        return sample_user

    def undo(self, client, token):
        return client.post('/api/account/email/undo', json={'token': token})

    def test_moves_the_account_back_and_ends_every_session(self, app, client, db, moved, fake_redis):
        client.post('/api/auth/login', json={'email': NEW_EMAIL, 'password': PASSWORD})
        assert len(fake_redis.tokens) == 1

        response = self.undo(client, undo_token(app, moved))

        assert response.status_code == 200
        assert response.get_json() == {'email': 'test@example.com'}
        assert current_email(db, moved) == 'test@example.com'
        assert fake_redis.tokens == set()
        assert client.get_cookie('__Secure-refresh_token', path='/api/auth') is None

    def test_works_after_the_password_and_the_address_change_again(self, app, client, db, moved, fake_redis):
        """Whoever moved the account may do both: the owner's link must
        still bring it back"""
        token = undo_token(app, moved)
        moved.set_password('the intruders passphrase')
        db.session.commit()
        client.post('/api/account/email/complete', json={
            'token': change_token(app, moved, 'third@example.com')})

        response = self.undo(client, token)

        assert response.status_code == 200
        assert current_email(db, moved) == 'test@example.com'

    def test_ends_a_change_asked_for_before_it(self, app, client, db, moved, fake_redis, jobs):
        pending = change_token(app, moved, 'third@example.com')
        self.undo(client, undo_token(app, moved))

        response = client.post('/api/account/email/complete', json={'token': pending})

        assert response.get_json()['error']['code'] == 'LINK_USED'

    def test_the_changes_own_link_cannot_move_it_away_again(
            self, app, client, db, sample_user, fake_redis, jobs):
        """Once back at its old address, the account matches what the
        change's link expects again: the undo must end that link too"""
        change = change_token(app, sample_user)
        client.post('/api/account/email/complete', json={'token': change})
        self.undo(client, undo_token(app, sample_user))

        response = client.post('/api/account/email/complete', json={'token': change})

        assert response.get_json()['error']['code'] == 'LINK_USED'
        assert current_email(db, sample_user) == 'test@example.com'

    def test_the_password_no_longer_logs_in(self, app, client, db, moved, fake_redis):
        """Whoever made the change may know it: the owner resets it next"""
        self.undo(client, undo_token(app, moved))

        response = client.post('/api/auth/login', json={'email': 'test@example.com', 'password': PASSWORD})

        assert response.status_code == 401

    def test_once_back_the_link_is_used(self, app, client, db, moved, fake_redis):
        token = undo_token(app, moved)
        self.undo(client, token)

        response = self.undo(client, token)

        assert response.get_json()['error']['code'] == 'LINK_USED'

    def test_an_old_address_taken_since(self, app, client, db, moved, fake_redis):
        """Freed by the change, and signed up for by someone else"""
        token = undo_token(app, moved)
        taken = User(email='test@example.com')
        taken.set_password('OtherPassword123')
        db.session.add(taken)
        db.session.commit()

        response = self.undo(client, token)

        assert response.status_code == 409
        assert response.get_json()['error']['code'] == 'EMAIL_ALREADY_REGISTERED'
        assert current_email(db, moved) == NEW_EMAIL

    def test_an_old_address_taken_between_the_check_and_the_write(
            self, app, client, db, moved, fake_redis, monkeypatch):
        token = undo_token(app, moved)
        taken = User(email='test@example.com')
        taken.set_password('OtherPassword123')
        db.session.add(taken)
        db.session.commit()
        monkeypatch.setattr(account_routes, 'select', lambda *a: select(User.id).where(User.id == -1))

        response = self.undo(client, token)

        assert response.status_code == 409
        assert current_email(db, moved) == NEW_EMAIL

    def test_without_redis_nothing_changes(self, app, client, db, moved, no_redis):
        response = self.undo(client, undo_token(app, moved))

        assert response.status_code == 503
        assert current_email(db, moved) == NEW_EMAIL

    def test_an_expired_link(self, app, client, db, moved, fake_redis):
        token = undo_token(app, moved, ago=EMAIL_UNDO_LINK_LIFETIME + timedelta(seconds=5))

        assert self.undo(client, token).get_json()['error']['code'] == 'LINK_EXPIRED'

    def test_a_link_just_before_it_expires(self, app, client, db, moved, fake_redis):
        token = undo_token(app, moved, ago=EMAIL_UNDO_LINK_LIFETIME - timedelta(seconds=5))

        assert self.undo(client, token).status_code == 200

    def test_a_replaced_account(self, app, client, db, moved, fake_redis):
        """Another account under the same id (a restored backup) is not the one the link names"""
        with app.app_context():
            token = make_link_token(EMAIL_UNDO_LINK, 'test@example.com', f'{moved.id}:12345')

        response = self.undo(client, token)

        assert response.get_json()['error']['code'] == 'LINK_INVALID'
        assert current_email(db, moved) == NEW_EMAIL

    def test_the_change_s_own_link_undoes_nothing(self, app, client, db, moved, fake_redis):
        """Another purpose"""
        with app.app_context():
            token = make_link_token(EMAIL_CHANGE_LINK, 'test@example.com', undo_state(db_user(moved)))

        assert self.undo(client, token).get_json()['error']['code'] == 'LINK_INVALID'

    def test_logs_the_undo(self, app, client, db, moved, fake_redis, security_events):
        self.undo(client, undo_token(app, moved))

        assert security_events()[-1] == {
            'message': 'email_change_undone', 'ip': '127.0.0.1', 'user_id': moved.id, 'sessions': 0}
