"""The job queue on real Redis: the app queues as its own user, the worker
runs jobs as its own, each within its ACL (docker-compose.test.yml)"""
import os

import pytest
from dramatiq import Worker
from flask import Blueprint
from redis.exceptions import ResponseError

from app import create_app
from app.utils.jobs import QUEUE_NAME, WORKER_MAINTENANCE_CHANCE, job

ran = []

blueprint = Blueprint('integration_jobs', __name__)


@job(blueprint)
def record(value):
    ran.append(value)


@pytest.fixture
def apps(integration_redis, monkeypatch):
    """The app, queueing as the app's Redis user, and the worker's app, as
    the worker's user, as their containers run them"""
    app = create_app()
    app.register_blueprint(blueprint)
    monkeypatch.setenv('REDIS_URL', os.environ['REDIS_WORKER_URL'])
    # The app's, which would replace the URL's password; the worker's
    # container gets none
    monkeypatch.delenv('REDIS_PASSWORD')
    worker_app = create_app()
    worker_app.register_blueprint(blueprint)
    ran.clear()
    yield app, worker_app
    for each in (app, worker_app):
        each.extensions['jobs_broker'].close()


def test_the_worker_runs_what_the_app_queued(apps):
    app, worker_app = apps
    with app.app_context():
        record.send('from the app')

    broker = worker_app.extensions['jobs_broker']
    broker.maintenance_chance = WORKER_MAINTENANCE_CHANCE
    worker = Worker(broker, worker_timeout=100)
    worker.start()
    broker.join(QUEUE_NAME)
    worker.join()
    worker.stop()

    assert ran == ['from the app']


def force_upkeep(broker):
    """Make the broker's next call tidy up after every worker it knows of,
    which calls KEYS"""
    broker.maintenance_chance = 1_000_000
    broker.heartbeat_timeout = 0
    broker.do_qsize(QUEUE_NAME)


def test_the_worker_may_run_the_queues_upkeep(apps):
    app, worker_app = apps
    with app.app_context():
        record.send('registers the app as a worker the upkeep tidies')

    force_upkeep(worker_app.extensions['jobs_broker'])

    assert worker_app.extensions['jobs_broker'].do_qsize(QUEUE_NAME) == 1


def test_the_app_may_not(apps):
    """Why the app's broker never tidies (maintenance_chance=0): its user may
    not run KEYS"""
    app, _ = apps
    with app.app_context():
        record.send('registers the app as a worker the upkeep tidies')

    with pytest.raises(ResponseError, match="User app has no permissions to run the 'keys' command"):
        force_upkeep(app.extensions['jobs_broker'])
