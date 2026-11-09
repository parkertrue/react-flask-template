import json
import smtplib

import pytest

from app.config import MailServer
from app.utils.log import JsonFormatter
from tests.conftest import FakeRedisService


@pytest.fixture(autouse=True)
def fake_redis(request):
    """Every test of the unit app gets an in-memory Redis token store.

    UnitTestConfig runs without Redis, but the app treats a missing store as
    an outage (login and refresh answer 503), so tests sign in through the
    same path production does. Request `no_redis` to test the outage itself.
    """
    if 'app' not in request.fixturenames:
        yield None
        return
    app = request.getfixturevalue('app')
    fake = FakeRedisService()
    app.extensions['redis_service'] = fake
    yield fake
    app.extensions['redis_service'] = None


@pytest.fixture
def no_redis(app, fake_redis):
    """The unit app with Redis unreachable"""
    app.extensions['redis_service'] = None


@pytest.fixture
def logged(caplog):
    """The app's log so far, each record as the JSON object production writes"""
    formatter = JsonFormatter()
    return lambda: [json.loads(formatter.format(record)) for record in caplog.records]


@pytest.fixture
def security_events(logged):
    """The security events logged so far, without their time and level"""
    def events():
        return [{k: v for k, v in line.items() if k not in ('time', 'level', 'logger')}
                for line in logged() if line['logger'] == 'app.security']
    return events


class FakeSmtp:
    """Stands in for smtplib.SMTP and SMTP_SSL: records what the app asked
    of the server, and what it sent, in its outbox"""

    def __init__(self, outbox, kind, host, port, timeout, context=None):
        self.outbox = outbox
        self.calls = [(kind, host, port, timeout, context)]
        outbox.connections.append(self)

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.calls.append(('quit',))

    def starttls(self, context):
        self.calls.append(('starttls', context))
        if self.outbox.fail_with:
            raise self.outbox.fail_with

    def login(self, user, password):
        self.calls.append(('login', user, password))

    def send_message(self, message):
        if self.outbox.fail_with:
            raise self.outbox.fail_with
        self.outbox.append(message)

    def close(self):
        self.calls.append(('close',))


class Outbox(list):
    """Every email sent, as an email.message.EmailMessage. Set fail_with to
    an exception for the server to raise."""

    def __init__(self):
        super().__init__()
        self.connections = []
        self.fail_with = None


@pytest.fixture
def outbox(app, monkeypatch):
    """The unit app's mail server, in memory: what it was sent, and how"""
    sent = Outbox()
    monkeypatch.setattr(smtplib, 'SMTP', lambda *a, **kw: FakeSmtp(sent, 'smtp', *a, **kw))
    monkeypatch.setattr(smtplib, 'SMTP_SSL', lambda *a, **kw: FakeSmtp(sent, 'smtps', *a, **kw))
    monkeypatch.setitem(app.config, 'EMAIL_SERVER', MailServer('tls', 'smtp.test', 465, 'mailer', 'mailpass'))
    monkeypatch.setitem(app.config, 'EMAIL_FROM', 'App <no-reply@app.test>')
    return sent
