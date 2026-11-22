"""auth/emails.py: what each email says and when it is not sent"""
from functools import partial
from urllib.parse import parse_qs, urlsplit

import pytest

from app.auth import emails as auth_emails
from app.auth.emails import (
    PASSWORD_RESET, PASSWORD_RESET_LINK, PASSWORD_RESET_LINK_HOURS, PASSWORD_RESET_LINK_LIFETIME,
    REGISTRATION_LINK, REGISTRATION_LINK_HOURS, REGISTRATION_LINK_LIFETIME,
    send_password_changed_email, send_password_reset_email, send_registration_email)
from app.utils.jobs import PermanentJobFailure
from app.utils.links import read_link_token
from tests.conftest import reset_token

# The notice after a reset, called with the address alone as the link's job is
reset_notice = partial(send_password_changed_email, how=PASSWORD_RESET)


class TestRegistrationEmail:
    """The job the worker runs: a link to finish signing up, or, for an
    address with an account, a note saying so"""

    @pytest.fixture(autouse=True)
    def app_url(self, app, monkeypatch):
        monkeypatch.setitem(app.config, 'APP_URL', 'https://app.test')

    @pytest.fixture(autouse=True)
    def app_name(self, app, monkeypatch):
        monkeypatch.setitem(app.config, 'APP_NAME', 'Some App')

    def link(self, message):
        """The link to act on: an email's first, before the privacy notice's"""
        links = [word for word in message.get_content().split() if word.startswith('https://')]
        assert links[1:] == ['https://app.test/privacy']
        return urlsplit(links[0])

    def test_a_new_address_gets_a_link_to_finish(self, app, db, outbox):
        send_registration_email('new@example.com')

        message, = outbox
        link = self.link(message)
        fragment = parse_qs(link.fragment)
        assert (message['To'], message['Subject']) == ('new@example.com', 'Finish signing up for Some App')
        assert (link.scheme, link.netloc, link.path, link.query) == (
            'https', 'app.test', '/signup/complete', '')
        # The token alone: it names the address, which the page reads from it
        assert set(fragment) == {'token'}
        assert read_link_token(
            REGISTRATION_LINK, fragment['token'][0], REGISTRATION_LINK_LIFETIME) == ('new@example.com', '')

    def test_a_registered_address_is_told_so_and_gets_no_token(self, app, db, sample_user, outbox):
        send_registration_email('test@example.com')

        message, = outbox
        assert (message['To'], message['Subject']) == ('test@example.com', 'You already have a Some App account')
        assert self.link(message).geturl() == 'https://app.test/login'

    # A new address, and one with an account (sample_user's)
    @pytest.mark.parametrize('email', ['new@example.com', 'test@example.com'])
    def test_each_names_the_app_and_ends_with_the_privacy_notice(
            self, app, db, sample_user, outbox, email):
        """The privacy notice says who runs the app and why this came"""
        send_registration_email(email)

        message, = outbox
        paragraphs = message.get_content().rstrip('\n').split('\n\n')
        assert 'sign up for Some App with this email address' in paragraphs[0]
        assert paragraphs[-1] == 'Who runs Some App, and what it keeps: https://app.test/privacy'

    @pytest.mark.parametrize('email', ['new@example.com', 'test@example.com'])
    def test_a_paragraph_is_one_line_for_the_reader_s_app_to_wrap(
            self, app, db, sample_user, outbox, email):
        send_registration_email(email)

        message, = outbox
        lines = message.get_content().rstrip('\n').split('\n')
        # Paragraphs alternate with blank lines, and none is split
        assert lines[1::2] == [''] * (len(lines) // 2)
        assert '' not in lines[::2]

    def test_the_link_s_lifetime_is_the_one_its_token_has(self, app, db, outbox):
        assert REGISTRATION_LINK_LIFETIME.total_seconds() == REGISTRATION_LINK_HOURS * 3600

    def test_says_how_long_the_link_works(self, app, db, outbox, monkeypatch):
        """Read from the constant, so changing it changes the email"""
        monkeypatch.setattr(auth_emails, 'REGISTRATION_LINK_HOURS', 36)

        send_registration_email('new@example.com')

        message, = outbox
        assert 'open this link within 36 hours:' in message.get_content()

    @pytest.mark.parametrize('email', [
        'victim@example.com, attacker@example.com',
        'Victim <attacker@example.com>',
        'victim@example.com\r\nBcc: attacker@example.com',
        'Victim@Example.COM',
    ], ids=['a list', 'a display name', 'a line break', 'not normalized'])
    def test_sends_nothing_to_what_the_form_would_refuse(self, app, db, outbox, email):
        """Only a write to the queue past the form can ask for these: the
        job must not mail them, nor be retried"""
        with pytest.raises(PermanentJobFailure):
            send_registration_email(email)

        assert outbox == []

    def test_the_worker_runs_it_from_the_queue(self, app, client, db, jobs, outbox, run_jobs):
        """The job the route queued is the one that sends: its name and
        arguments line up"""
        client.post('/api/auth/register', json={'email': 'new@example.com'})
        run_jobs()

        assert [message['To'] for message in outbox] == ['new@example.com']


class TestPasswordResetEmails:
    """The jobs the worker runs: the reset link, to an address with an
    account alone, and the notice once the password has changed"""

    @pytest.fixture(autouse=True)
    def app_url(self, app, monkeypatch):
        monkeypatch.setitem(app.config, 'APP_URL', 'https://app.test')

    @pytest.fixture(autouse=True)
    def app_name(self, app, monkeypatch):
        monkeypatch.setitem(app.config, 'APP_NAME', 'Some App')

    def link(self, message):
        """The link to act on: an email's first, before the privacy notice's"""
        links = [word for word in message.get_content().split() if word.startswith('https://')]
        assert links[1:] == ['https://app.test/privacy']
        return urlsplit(links[0])

    def test_an_account_gets_a_link_to_reset_its_password(self, app, db, sample_user, outbox):
        send_password_reset_email('test@example.com')

        message, = outbox
        link = self.link(message)
        fragment = parse_qs(link.fragment)
        assert (message['To'], message['Subject']) == ('test@example.com', 'Reset your Some App password')
        assert (link.scheme, link.netloc, link.path, link.query) == (
            'https', 'app.test', '/password-reset/complete', '')
        assert set(fragment) == {'token'}
        # The account's address, and the password it has now
        assert read_link_token(
            PASSWORD_RESET_LINK, fragment['token'][0], PASSWORD_RESET_LINK_LIFETIME) == (
            'test@example.com', sample_user.password_state)

    def test_the_link_s_token_is_not_compressed(self, app, db, sample_user, outbox):
        """The page reads the address for password managers from the
        token's payload, which it cannot from a compressed one ('.' first)"""
        send_password_reset_email('test@example.com')

        message, = outbox
        token = parse_qs(self.link(message).fragment)['token'][0]
        assert not token.startswith('.')

    def test_an_address_without_an_account_gets_nothing(self, app, db, sample_user, outbox):
        send_password_reset_email('new@example.com')

        assert outbox == []

    @pytest.mark.parametrize(('send', 'opening'), [
        (send_password_reset_email,
         'Someone, hopefully you, asked to reset the password of your Some App account.'),
        (reset_notice,
         'The password of your Some App account was just reset with a link sent to this address, '
         'and every device signed in to the account was logged out.'),
    ], ids=['the link', 'the notice'])
    def test_each_names_the_app_in_one_line_paragraphs_and_ends_with_the_privacy_notice(
            self, app, db, sample_user, outbox, send, opening):
        send('test@example.com')

        message, = outbox
        paragraphs = message.get_content().rstrip('\n').split('\n\n')
        assert paragraphs[0] == opening
        assert paragraphs[-1] == 'Who runs Some App, and what it keeps: https://app.test/privacy'
        assert '\n' not in ''.join(paragraphs)

    def test_the_link_s_lifetime_is_the_one_its_token_has(self):
        assert PASSWORD_RESET_LINK_LIFETIME.total_seconds() == PASSWORD_RESET_LINK_HOURS * 3600

    @pytest.mark.parametrize(('hours', 'said'), [(1, '1 hour'), (2, '2 hours')])
    def test_says_how_long_the_link_works(self, app, db, sample_user, outbox, monkeypatch, hours, said):
        """Read from the constant, so changing it changes the email"""
        monkeypatch.setattr(auth_emails, 'PASSWORD_RESET_LINK_HOURS', hours)

        send_password_reset_email('test@example.com')

        message, = outbox
        assert f'open this link within {said}:' in message.get_content()

    def test_the_notice_after_a_change_says_so(self, app, db, sample_user, outbox):
        """Changed from a signed-in session, not through this inbox"""
        send_password_changed_email('test@example.com', 'change')

        message, = outbox
        paragraphs = message.get_content().rstrip('\n').split('\n\n')
        assert paragraphs[:2] == [
            'The password of your Some App account was just changed from a signed-in session, '
            'and every other device signed in to the account was logged out.',
            "If it wasn't you, someone else knows your password: reset it here, which logs out "
            'every device:']
        assert self.link(message).geturl() == 'https://app.test/password-reset'

    def test_the_notice_refuses_another_way(self, app, db, sample_user, outbox):
        with pytest.raises(PermanentJobFailure):
            send_password_changed_email('test@example.com', 'guessed')

        assert outbox == []

    def test_the_notice_links_to_a_new_reset(self, app, db, sample_user, outbox):
        """For an owner who did not ask for it, and must take the account back"""
        send_password_changed_email('test@example.com', PASSWORD_RESET)

        message, = outbox
        assert (message['To'], message['Subject']) == (
            'test@example.com', 'Your Some App password was changed')
        assert self.link(message).geturl() == 'https://app.test/password-reset'

    @pytest.mark.parametrize('send', [send_password_reset_email, reset_notice],
                             ids=['the link', 'the notice'])
    @pytest.mark.parametrize('email', [
        'victim@example.com, attacker@example.com',
        'Victim <attacker@example.com>',
        'victim@example.com\r\nBcc: attacker@example.com',
        'Test@Example.COM',
    ], ids=['a list', 'a display name', 'a line break', 'not normalized'])
    def test_sends_nothing_to_what_the_form_would_refuse(self, app, db, sample_user, outbox, send, email):
        with pytest.raises(PermanentJobFailure):
            send(email)

        assert outbox == []

    def test_the_worker_runs_both_from_the_queue(self, app, client, db, sample_user, jobs, outbox, run_jobs):
        """The jobs the routes queued are the ones that send"""
        client.post('/api/auth/password-reset', json={'email': 'test@example.com'})
        client.post('/api/auth/password-reset/complete', json={
            'token': reset_token(app, 'test@example.com'), 'password': 'a valid passphrase'})
        run_jobs()

        assert sorted(message['Subject'] for message in outbox) == [
            'Reset your Some App password', 'Your Some App password was changed']
