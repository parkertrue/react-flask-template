"""The jobs an email change queues: the link to the new address (or a note
that it has an account), and the notice to the old one, with the link back"""
from urllib.parse import parse_qs, urlsplit

import pytest
from dramatiq import Worker

from app.account import emails as account_emails
from app.account.emails import (
    EMAIL_CHANGE_LINK, EMAIL_CHANGE_LINK_HOURS, EMAIL_CHANGE_LINK_LIFETIME, EMAIL_UNDO_LINK,
    EMAIL_UNDO_LINK_LIFETIME, change_state, masked, send_email_change_email,
    send_email_changed_email, undo_state)
from app.utils.jobs import QUEUE_NAME, PermanentJobFailure
from app.utils.links import read_link_token


@pytest.fixture(autouse=True)
def app_url(app, monkeypatch):
    monkeypatch.setitem(app.config, 'APP_URL', 'https://app.test')
    monkeypatch.setitem(app.config, 'APP_NAME', 'Some App')


def link(message):
    """The link to act on: an email's first, before the privacy notice's"""
    links = [word for word in message.get_content().split() if word.startswith('https://')]
    assert links[1:] == ['https://app.test/privacy']
    return urlsplit(links[0])


def token(message):
    return parse_qs(link(message).fragment)['token'][0]


class TestEmailChangeEmail:
    def test_a_free_address_gets_the_link(self, app, db, sample_user, outbox):
        send_email_change_email(sample_user.id, 'new@example.com')

        message, = outbox
        assert (message['To'], message['Subject']) == ('new@example.com', 'Confirm your new Some App email')
        assert (link(message).path, link(message).query) == ('/account/email/complete', '')
        assert read_link_token(EMAIL_CHANGE_LINK, token(message), EMAIL_CHANGE_LINK_LIFETIME) == (
            'new@example.com', change_state(sample_user))
        # Uncompressed, so the page can read its address
        assert not token(message).startswith('.')

    def test_says_how_long_the_link_works(self, app, db, sample_user, outbox, monkeypatch):
        monkeypatch.setattr(account_emails, 'EMAIL_CHANGE_LINK_HOURS', 36)

        send_email_change_email(sample_user.id, 'new@example.com')

        message, = outbox
        assert 'open this link within 36 hours:' in message.get_content()

    def test_the_link_s_lifetime_is_the_one_its_token_has(self):
        assert EMAIL_CHANGE_LINK_LIFETIME.total_seconds() == EMAIL_CHANGE_LINK_HOURS * 3600

    def test_an_address_with_an_account_is_told_so_and_gets_no_token(
            self, app, db, sample_user, second_user, outbox):
        send_email_change_email(sample_user.id, 'other@example.com')

        message, = outbox
        assert (message['To'], message['Subject']) == ('other@example.com', 'You already have a Some App account')
        assert link(message).geturl() == 'https://app.test/login'

    @pytest.mark.parametrize('email', ['test@example.com', 'TEST@example.com'])
    def test_nothing_for_the_account_s_own_address(self, app, db, sample_user, outbox, email):
        send_email_change_email(sample_user.id, email)

        assert outbox == []

    def test_nothing_for_an_account_deleted_since(self, app, db, outbox):
        send_email_change_email(12345, 'new@example.com')

        assert outbox == []

    @pytest.mark.parametrize('send', [send_email_change_email, send_email_changed_email],
                             ids=['the link', 'the notice'])
    @pytest.mark.parametrize('email', [
        'victim@example.com, attacker@example.com', 'Victim <attacker@example.com>', 'Victim@Example.COM',
    ], ids=['a list', 'a display name', 'not normalized'])
    def test_sends_nothing_to_what_the_form_would_refuse(self, app, db, sample_user, outbox, send, email):
        with pytest.raises(PermanentJobFailure):
            send(sample_user.id, email)

        assert outbox == []


class TestEmailChangedEmail:
    def test_tells_the_old_address_with_the_link_back(self, app, db, sample_user, outbox):
        sample_user.email = 'new@example.com'
        db.session.commit()

        send_email_changed_email(sample_user.id, 'test@example.com')

        message, = outbox
        paragraphs = message.get_content().rstrip('\n').split('\n\n')
        assert (message['To'], message['Subject']) == ('test@example.com', 'Your Some App email was changed')
        assert paragraphs[0] == 'The email address of your Some App account was just changed to n***@example.com.'
        assert 'within 7 days' in paragraphs[1]
        assert (link(message).path, link(message).query) == ('/account/email/undo', '')
        assert read_link_token(EMAIL_UNDO_LINK, token(message), EMAIL_UNDO_LINK_LIFETIME) == (
            'test@example.com', undo_state(sample_user))
        assert paragraphs[-1] == 'Who runs Some App, and what it keeps: https://app.test/privacy'

    def test_nothing_for_an_account_deleted_since(self, app, db, outbox):
        send_email_changed_email(12345, 'test@example.com')

        assert outbox == []


@pytest.mark.parametrize(('email', 'shown'), [
    ('new@example.com', 'n***@example.com'), ('a@xn--bcher-kva.de', 'a***@xn--bcher-kva.de')])
def test_masked(email, shown):
    assert masked(email) == shown


def test_the_worker_runs_both_from_the_queue(app, client, db, sample_user, auth_headers, jobs, outbox):
    """The jobs the routes queued are the ones that send"""
    client.post('/api/account/email', headers=auth_headers,
                json={'email': 'new@example.com', 'password': 'TestPassword123'})
    broker = app.extensions['jobs_broker']

    def run():
        worker = Worker(broker, worker_timeout=10)
        worker.start()
        broker.join(QUEUE_NAME, fail_fast=True)
        worker.stop()
    run()
    client.post('/api/account/email/complete', json={'token': token(outbox[0])})
    run()

    assert [(m['To'], m['Subject']) for m in outbox] == [
        ('new@example.com', 'Confirm your new Some App email'),
        ('test@example.com', 'Your Some App email was changed')]
