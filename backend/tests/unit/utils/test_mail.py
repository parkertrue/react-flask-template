"""Sending email, through the in-memory mail server (outbox, in conftest.py)"""
import smtplib
import ssl

import pytest

from app.config import MailServer
from app.utils.jobs import PermanentJobFailure
from app.utils.mail import EmailNotSent, send_email

ADDRESS = 'someone@example.com'


def send():
    send_email(ADDRESS, 'Hello', 'Line one\nLine two\n')


def test_sends_a_plain_text_email(outbox):
    send()

    message, = outbox
    assert (message['From'], message['To'], message['Subject']) == (
        'App <no-reply@app.test>', ADDRESS, 'Hello')
    assert message.get_content_type() == 'text/plain'
    assert message.get_content() == 'Line one\nLine two\n'


def test_says_a_program_sent_it(outbox):
    """So no mail server answers it with an out-of-office reply"""
    send()

    assert outbox[0]['Auto-Submitted'] == 'auto-generated'


def test_dates_and_names_each_email_from_the_senders_domain(outbox):
    send()
    send()

    first, second = outbox
    assert first['Date'].endswith('+0000')
    assert first['Message-ID'].endswith('@app.test>')
    assert first['Message-ID'] != second['Message-ID']


def tls_checks(context):
    """Whether an SSL context checks the server's certificate and name"""
    return (context.verify_mode, context.check_hostname) == (ssl.CERT_REQUIRED, True)


class TestConnection:
    def test_smtps_is_tls_from_the_start(self, outbox):
        send()

        kind, host, port, timeout, context = outbox.connections[0].calls[0]
        assert (kind, host, port, timeout) == ('smtps', 'smtp.test', 465, 10)
        assert tls_checks(context)

    def test_starttls_upgrades_before_logging_in(self, outbox, app, monkeypatch):
        monkeypatch.setitem(app.config, 'EMAIL_SERVER',
                            MailServer('starttls', 'smtp.test', 587, 'mailer', 'mailpass'))

        send()

        calls = outbox.connections[0].calls
        assert calls[0][:3] == ('smtp', 'smtp.test', 587)
        assert [call[0] for call in calls[1:]] == ['starttls', 'login', 'quit']
        assert tls_checks(calls[1][1])

    def test_a_server_without_starttls_is_never_sent_to_in_the_clear(self, outbox, app, monkeypatch):
        monkeypatch.setitem(app.config, 'EMAIL_SERVER',
                            MailServer('starttls', 'smtp.test', 587, 'mailer', 'mailpass'))
        outbox.fail_with = smtplib.SMTPNotSupportedError('STARTTLS extension not supported by server.')

        with pytest.raises(EmailNotSent, match='SMTPNotSupportedError'):
            send()

        assert [call[0] for call in outbox.connections[0].calls[1:]] == ['starttls', 'close']
        assert outbox == []

    def test_plain_smtp_for_a_mail_catcher(self, outbox, app, monkeypatch):
        monkeypatch.setitem(app.config, 'EMAIL_SERVER', MailServer('none', 'mailpit', 1025, None))

        send()

        calls = outbox.connections[0].calls
        assert calls[0][:3] == ('smtp', 'mailpit', 1025)
        # No login without a user
        assert [call[0] for call in calls[1:]] == ['quit']
        assert len(outbox) == 1

    def test_logs_in_as_the_urls_user(self, outbox):
        send()

        assert outbox.connections[0].calls[1] == ('login', 'mailer', 'mailpass')


@pytest.mark.parametrize('setting', ['EMAIL_SERVER', 'EMAIL_FROM'])
def test_refuses_to_send_without_its_settings(outbox, app, monkeypatch, setting):
    monkeypatch.setitem(app.config, setting, None)

    with pytest.raises(RuntimeError, match='EMAIL_URL and EMAIL_FROM must be set'):
        send()


class TestFailures:
    """Each failure is retried unless the address itself was refused, and
    none quotes the server, whose words often hold the address"""

    @pytest.mark.parametrize('error, raised', [
        (smtplib.SMTPRecipientsRefused({ADDRESS: (550, b'5.1.1 <someone@example.com> unknown')}),
         PermanentJobFailure),
        (smtplib.SMTPRecipientsRefused({ADDRESS: (452, b'4.2.2 <someone@example.com> full')}),
         EmailNotSent),
        (smtplib.SMTPDataError(554, b'5.7.1 Message from someone@example.com rejected'),
         PermanentJobFailure),
        (smtplib.SMTPDataError(451, b'4.7.1 Greylisted, try again later'), EmailNotSent),
        # A refused login or sender is the deployment's settings: once fixed,
        # a retry gets through
        (smtplib.SMTPAuthenticationError(535, b'5.7.8 Bad credentials'), EmailNotSent),
        (smtplib.SMTPSenderRefused(553, b'5.7.1 Sender not allowed', 'no-reply@app.test'),
         EmailNotSent),
        (smtplib.SMTPServerDisconnected('Connection unexpectedly closed'), EmailNotSent),
        (TimeoutError('timed out'), EmailNotSent),
        (ssl.SSLCertVerificationError('certificate verify failed'), EmailNotSent),
    ])
    def test_kind_of_failure(self, outbox, error, raised):
        outbox.fail_with = error

        with pytest.raises(raised) as caught:
            send()

        assert 'someone' not in str(caught.value)
        # Raised from None, so a logged traceback holds no server reply either
        assert (caught.value.__cause__, caught.value.__suppress_context__) == (None, True)

    @pytest.mark.parametrize('code, raised, message', [
        (500, PermanentJobFailure, 'The mail server refused the email: 500'),
        (550, PermanentJobFailure, 'The mail server refused the email: 550'),
        (452, EmailNotSent, 'The mail server deferred the email: 452'),
    ])
    def test_names_the_code(self, outbox, code, raised, message):
        outbox.fail_with = smtplib.SMTPRecipientsRefused({ADDRESS: (code, b'')})

        with pytest.raises(raised, match=message):
            send()


def test_logs_each_email_sent_without_its_address(outbox, logged):
    send()

    line, = [line for line in logged() if line['logger'] == 'app.mail']
    assert (line['message'], line['message_id']) == ('email_sent', outbox[0]['Message-ID'])
    assert ADDRESS not in str(line)
