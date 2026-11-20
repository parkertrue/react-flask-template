import json
import smtplib

import pytest
from dramatiq import Message, Worker

from app.config import MailServer
from app.utils import passwords
from app.utils.jobs import QUEUE_NAME
from app.utils.log import JsonFormatter
from tests.conftest import FakeRedisService

# Saved before cheap_password_hashing patches it, for the tests that pin it
PRODUCTION_HASH_METHOD = passwords.PASSWORD_HASH_METHOD


@pytest.fixture(autouse=True)
def cheap_password_hashing(monkeypatch):
    """Hash at the smallest scrypt cost Werkzeug takes (n=256, under 1ms).
    Production's costs ~80ms a hash, which was most of the suite's run
    time. Verifying reads the cost from the hash, so cheap hashes stay
    cheap; tests/unit/utils/test_passwords.py pins production's."""
    monkeypatch.setattr(passwords, 'PASSWORD_HASH_METHOD', 'scrypt:256:8:1')


@pytest.fixture(autouse=True)
def fake_redis(request):
    """Every test of the unit app gets an in-memory Redis token store.

    UnitTestConfig runs without Redis, but the app treats a missing store as
    an outage (login and refresh answer 503), so tests sign in through the
    same path production does. Request `no_redis` to test the outage itself.
    A Redis call that failed to connect makes the app skip Redis for a few
    seconds (redis_unreachable); that ends with the test.
    """
    if 'app' not in request.fixturenames:
        yield None
        return
    app = request.getfixturevalue('app')
    fake = FakeRedisService()
    app.extensions['redis_service'] = fake
    yield fake
    app.extensions['redis_service'] = None
    app.extensions.pop('redis_retry_at', None)


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


@pytest.fixture
def run_jobs(app):
    """Run what is queued with a real worker, retries included, to the end:
    run_jobs(), or run_jobs(other_app). A job that fails stops it with its
    error, unless fail_fast=False, for a test of a job that fails."""
    def run(on=None, *, fail_fast=True):
        broker = (on or app).extensions['jobs_broker']
        worker = Worker(broker, worker_timeout=10)
        worker.start()
        try:
            broker.join(QUEUE_NAME, fail_fast=fail_fast)
            worker.join()
        finally:
            worker.stop()
    return run


@pytest.fixture
def jobs(app):
    """The jobs queued so far, as (name, arguments); the queue starts empty"""
    broker = app.extensions['jobs_broker']
    broker.flush_all()
    yield lambda: [(message.actor_name, message.args) for message in
                   map(Message.decode, list(broker.queues[QUEUE_NAME].queue))]
    broker.flush_all()
