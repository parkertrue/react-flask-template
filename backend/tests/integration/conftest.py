"""What every integration test shares: Redis cleaned after each, and a
worker that runs the queued jobs, for the tests of the email the app sends
(what it sends arrives in Mailpit, mailpit.py)"""
import os

import pytest
from dramatiq import Worker

from app import create_app
from app.utils.jobs import QUEUE_NAME
from tests.conftest import close_app
from tests.integration.mailpit import mailpit


@pytest.fixture
def worker(integration_app, integration_db, integration_redis, monkeypatch):
    """Runs the queued jobs as the worker container does: its own app, as
    the worker's Redis user"""
    mailpit('/messages', method='DELETE')
    monkeypatch.setenv('REDIS_URL', os.environ['REDIS_WORKER_URL'])
    # The app's password, which would replace the URL's; the container gets none
    monkeypatch.delenv('REDIS_PASSWORD')
    worker_app = create_app()

    def run():
        broker = worker_app.extensions['jobs_broker']
        running = Worker(broker, worker_timeout=100)
        running.start()
        broker.join(QUEUE_NAME)
        running.join()
        running.stop()
    yield run
    close_app(worker_app)
    mailpit('/messages', method='DELETE')


@pytest.fixture(autouse=True)
def clean_redis(integration_redis):
    """Every integration test leaves Redis as it found it, not just those
    that ask for integration_redis: a session one leaves (a login, a
    session_token) would land on the next test's user, since each fresh
    database hands out the same ids"""
    yield
