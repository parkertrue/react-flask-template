"""Background jobs on Dramatiq's in-memory broker, with jobs of their own:
the app's belong to its features"""
import json
import logging
import threading
from datetime import timedelta
from unittest.mock import MagicMock

import pytest
from dramatiq import Message, Worker
from dramatiq.brokers.redis import RedisBroker
from flask import Blueprint, current_app
from redis import ConnectionError as RedisConnectionError

from app import create_app
from app.utils import jobs
from app.utils.errors import SERVICE_UNAVAILABLE_MESSAGE
from app.utils.jobs import QUEUE_NAME, PermanentJobFailure, job


@pytest.fixture
def make_app(app, monkeypatch):
    """A fresh unit app, with each blueprint given registered on it.

    A fresh app per test: the session's has its broker and actors already.
    Retries wait a millisecond rather than 15s, and give up after two.
    """
    monkeypatch.setattr(jobs, 'MIN_BACKOFF', timedelta(milliseconds=1))
    monkeypatch.setattr(jobs, 'MAX_BACKOFF', timedelta(milliseconds=1))
    monkeypatch.setattr(jobs, 'MAX_RETRIES', 2)

    def make(*blueprints):
        fresh = create_app()
        for blueprint in blueprints:
            fresh.register_blueprint(blueprint)
        return fresh
    return make


def run_jobs(app):
    """Run every queued job, retries included, to the end"""
    broker = app.extensions['jobs_broker']
    worker = Worker(broker, worker_timeout=10)
    worker.start()
    broker.join(QUEUE_NAME, fail_fast=False)
    worker.join()
    worker.stop()


def queued(app):
    """The messages waiting on the app's queue"""
    queue = app.extensions['jobs_broker'].queues[QUEUE_NAME]
    return [Message.decode(data) for data in list(queue.queue)]


class TestSend:
    @pytest.fixture
    def tidy(self, make_app):
        blueprint = Blueprint('things', __name__)

        @job(blueprint)
        def tidy(thing_id, label):
            pass

        app = make_app(blueprint)
        return app, tidy

    def test_queues_a_message_naming_the_job(self, tidy):
        app, declared = tidy

        with app.app_context():
            declared.send(7, 'a label')

        messages = queued(app)
        assert [(m.actor_name, m.args) for m in messages] == [('things.tidy', (7, 'a label'))]

    def test_the_message_is_json(self, tidy):
        """Never pickle: a message written to Redis must not run code"""
        app, declared = tidy

        with app.app_context():
            declared.send(7, 'a label')

        data = app.extensions['jobs_broker'].queues[QUEUE_NAME].queue[0]
        assert json.loads(data)['args'] == [7, 'a label']

    def test_redis_down_is_a_503(self, tidy, monkeypatch):
        app, declared = tidy

        @app.route('/_tidy', methods=['POST'])
        def queue_tidy():
            declared.send(7, 'a label')
            return '', 204

        def refuse(message, *, delay=None):
            raise RedisConnectionError('Connection refused')
        monkeypatch.setattr(app.extensions['jobs_broker'], 'enqueue', refuse)

        response = app.test_client().post('/_tidy')

        assert response.status_code == 503
        assert response.get_json() == {'error': {
            'code': 'SERVICE_UNAVAILABLE', 'message': SERVICE_UNAVAILABLE_MESSAGE}}


class TestRun:
    def test_runs_in_an_app_context(self, make_app):
        seen = []
        blueprint = Blueprint('things', __name__)

        @job(blueprint)
        def record(thing_id):
            seen.append((thing_id, current_app.name))

        app = make_app(blueprint)
        with app.app_context():
            record.send(7)

        run_jobs(app)

        assert seen == [(7, app.name)]

    def test_a_failing_job_is_retried_then_kept_as_failed(self, make_app):
        attempts = []
        blueprint = Blueprint('things', __name__)

        @job(blueprint)
        def flaky():
            attempts.append(1)
            raise ConnectionError('the mail server is down')

        app = make_app(blueprint)
        with app.app_context():
            flaky.send()

        run_jobs(app)

        # The first try and MAX_RETRIES more
        assert len(attempts) == 3
        assert len(app.extensions['jobs_broker'].dead_letters) == 1

    def test_a_permanent_failure_is_not_retried(self, make_app):
        attempts = []
        blueprint = Blueprint('things', __name__)

        @job(blueprint)
        def refused():
            attempts.append(1)
            raise PermanentJobFailure('the address does not exist')

        app = make_app(blueprint)
        with app.app_context():
            refused.send()

        run_jobs(app)

        assert len(attempts) == 1
        assert len(app.extensions['jobs_broker'].dead_letters) == 1


def test_closing_closes_a_redis_brokers_client(app, monkeypatch):
    """Dramatiq's RedisBroker.close closes nothing, and the client is ours"""
    client = MagicMock()
    monkeypatch.setitem(app.extensions, 'jobs_broker', RedisBroker(client=client))

    jobs.close_jobs(app)

    client.close.assert_called_once_with()


def test_logs_name_a_message_by_its_id_alone():
    """Dramatiq logs a failed message with its arguments: an email address"""
    message = Message(queue_name=QUEUE_NAME, actor_name='things.tidy',
                      args=('someone@example.com',), kwargs={}, options={})
    record = logging.LogRecord('dramatiq.worker', logging.ERROR, __file__, 1,
                               'Failed to process message %s.', (message,), None)

    jobs._MessageIdOnly().filter(record)

    assert record.getMessage() == f'Failed to process message {message.message_id}.'


class TestRunWorker:
    @pytest.fixture
    def worker(self, make_app, monkeypatch, tmp_path):
        """run_worker on a thread, with the signal handlers it installs kept
        here: a thread may not install its own. Yields the app, the job's
        calls and the handler that stops it."""
        handlers = {}
        monkeypatch.setattr(jobs.signal, 'signal', lambda signum, handler: handlers.setdefault(signum, handler))
        monkeypatch.setattr(jobs, 'READY_FILE', tmp_path / 'worker-ready')
        seen = []
        blueprint = Blueprint('things', __name__)

        @job(blueprint)
        def record(thing_id):
            seen.append(thing_id)

        app = make_app(blueprint)
        thread = threading.Thread(target=jobs.run_worker, args=(app,))
        thread.start()
        yield app, record, seen, handlers
        handlers[jobs.signal.SIGTERM](jobs.signal.SIGTERM, None)
        thread.join(timeout=10)
        logging.getLogger('dramatiq').handlers.clear()

    def eventually(self, condition):
        """Whether condition comes true within 5s"""
        for _ in range(500):
            if condition():
                return True
            threading.Event().wait(0.01)
        return False

    def test_runs_jobs_once_ready(self, worker):
        app, record, seen, _ = worker
        assert self.eventually(jobs.READY_FILE.exists)

        with app.app_context():
            record.send(7)

        assert self.eventually(lambda: seen == [7])

    @pytest.mark.parametrize('signum', ['SIGTERM', 'SIGINT'])
    def test_a_signal_stops_it(self, worker, signum):
        _, _, _, handlers = worker
        assert self.eventually(jobs.READY_FILE.exists)

        handlers[getattr(jobs.signal, signum)](getattr(jobs.signal, signum), None)

        assert self.eventually(lambda: not jobs.READY_FILE.exists())
