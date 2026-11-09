"""Sending email, from a job the worker runs (jobs.py), never from a request.

Over SMTP, which every mail provider accepts (docs/deployment.md, Sending
Email), so no provider's own API or library is needed. The server is
EMAIL_URL (config.py's MailServer); production requires TLS, and smtplib
checks the server's certificate and name against the system's CAs.

A failure raises EmailNotSent, which the job's retries try again, or
PermanentJobFailure when the server refused the address itself. Neither
carries the server's own words, which often quote the address: Dramatiq
logs a failed job's exception.
"""
import smtplib
import ssl
from email.message import EmailMessage
from email.utils import formatdate, make_msgid, parseaddr

from flask import current_app

from app.config import MailServer
from app.utils.jobs import PermanentJobFailure

# Each connect, command and reply; a server that stops answering frees the
# worker's thread well before the job's time limit
SMTP_TIMEOUT_SECONDS = 10


class EmailNotSent(Exception):
    """The mail server could not be reached or turned the email away for now"""


def send_email(to: str, subject: str, body: str) -> None:
    """Send a plain-text email from EMAIL_FROM.

    Plain text alone: every client shows it, and it carries no tracking,
    remote images or markup to sanitize (DECISIONS.md).
    """
    server: MailServer | None = current_app.config['EMAIL_SERVER']
    sender: str | None = current_app.config['EMAIL_FROM']
    if server is None or sender is None:
        raise RuntimeError('EMAIL_URL and EMAIL_FROM must be set to send email')

    message = EmailMessage()
    message['From'] = sender
    message['To'] = to
    message['Subject'] = subject
    message['Date'] = formatdate(usegmt=True)
    message['Message-ID'] = make_msgid(domain=parseaddr(sender)[1].rpartition('@')[2])
    # Tells mail servers and clients a program sent it, so none answers it
    # with an out-of-office reply (RFC 3834)
    message['Auto-Submitted'] = 'auto-generated'
    message.set_content(body)

    try:
        with _connect(server) as smtp:
            if server.username:
                smtp.login(server.username, server.password or '')
            smtp.send_message(message)
    except smtplib.SMTPRecipientsRefused as e:
        codes = sorted(code for code, _ in e.recipients.values())
        raise _refused(codes[0]) from None
    except smtplib.SMTPDataError as e:
        raise _refused(e.smtp_code) from None
    except smtplib.SMTPResponseException as e:
        # A refused login or sender: the server's settings, not the address,
        # so a retry may succeed once they are fixed
        raise EmailNotSent(f'The mail server answered {e.smtp_code}') from None
    except (smtplib.SMTPException, OSError) as e:
        # Unreachable, timed out, no STARTTLS, or a certificate that failed
        # its check. Only the kind: an SMTP error's text may quote the address.
        raise EmailNotSent(f'Could not send through the mail server: {type(e).__name__}') from None

    current_app.logger.getChild('mail').info(
        'email_sent', extra={'fields': {'message_id': message['Message-ID']}})


def _refused(code: int) -> Exception:
    """A 5xx turns this address or message away for good; anything else
    (a full mailbox, greylisting) may pass later"""
    if 500 <= code < 600:
        return PermanentJobFailure(f'The mail server refused the email: {code}')
    return EmailNotSent(f'The mail server deferred the email: {code}')


def _connect(server: MailServer) -> smtplib.SMTP:
    if server.security == 'tls':
        return smtplib.SMTP_SSL(server.host, server.port, timeout=SMTP_TIMEOUT_SECONDS,
                                context=ssl.create_default_context())
    smtp = smtplib.SMTP(server.host, server.port, timeout=SMTP_TIMEOUT_SECONDS)
    if server.security == 'starttls':
        try:
            # Raises SMTPNotSupportedError when the server offers no STARTTLS:
            # never fall back to sending in the clear
            smtp.starttls(context=ssl.create_default_context())
        except BaseException:
            smtp.close()
            raise
    return smtp
