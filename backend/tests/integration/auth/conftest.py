"""A worker that runs the queued jobs, for the auth feature's integration
tests: what it sends arrives in Mailpit (mailpit.py)"""
import os

import pytest
from dramatiq import Worker

from app import create_app
from app.utils.jobs import QUEUE_NAME
from tests.conftest import close_app
from tests.integration.auth.mailpit import mailpit


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
