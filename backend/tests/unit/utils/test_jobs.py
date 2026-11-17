"""Background jobs on Dramatiq's in-memory broker, with jobs of their own:
the app's belong to its features"""
import io
import json
import logging
import threading
from datetime import timedelta
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest
from dramatiq import Message, Worker
from dramatiq.brokers.redis import RedisBroker
from dramatiq.middleware import Retries, TimeLimit
from flask import Blueprint, current_app
from redis import ConnectionError as RedisConnectionError
from redis import ResponseError, TimeoutError as RedisTimeoutError

from app import create_app
from app.utils import jobs
from app.utils.errors import SERVICE_UNAVAILABLE_MESSAGE
from app.utils.jobs import QUEUE_NAME, JobQueueUnavailable, PermanentJobFailure, job
from app.utils.redis_service import RedisService, redis_unreachable


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

    @pytest.mark.parametrize(('error', 'unreachable'), [
        (RedisConnectionError('Connection refused'), True),
        (RedisTimeoutError('Timeout reading from socket'), True),
        (ResponseError('NOPERM this user has no permissions'), False),
    ], ids=['refused', 'timed out', 'refused by the ACL'])
    def test_only_an_unreachable_redis_is_skipped_for_a_while(
            self, tidy, monkeypatch, error, unreachable):
        """A full Redis or a NOPERM answers fast; only unreachable means wait"""
        app, declared = tidy

        def refuse(message, *, delay=None):
            raise error
        monkeypatch.setattr(app.extensions['jobs_broker'], 'enqueue', refuse)

        with app.app_context(), pytest.raises(JobQueueUnavailable):
            declared.send(7, 'a label')

        assert redis_unreachable(app) is unreachable

    def test_a_token_store_that_failed_to_connect_skips_the_queue(self, tidy, monkeypatch):
        """The token store and the queue share one state: whichever fails
        first spares the other the wait"""
        app, declared = tidy
        enqueued = []
        monkeypatch.setattr(app.extensions['jobs_broker'], 'enqueue',
                            lambda message, *, delay=None: enqueued.append(message))
        with patch('app.utils.redis_service.redis.Redis'):
            service = RedisService('redis://app:secret@redis:6379/0', max_connections=5)
        service.get_client().zscore.side_effect = RedisConnectionError('Connection refused')

        with app.app_context():
            assert service.is_token_valid(1, 'jti') is None
            with pytest.raises(JobQueueUnavailable):
                declared.send(7, 'a label')

        assert enqueued == []


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


def test_the_job_settings(app):
    """What CLAUDE.md and docs/deployment.md promise, as literals: ten
    retries backing off from 15s to an hour, and a minute per try"""
    middleware = {type(each): each for each in app.extensions['jobs_broker'].middleware}
    retries, time_limit = middleware[Retries], middleware[TimeLimit]

    assert (retries.max_retries, retries.min_backoff, retries.max_backoff) == (10, 15_000, 3_600_000)
    assert time_limit.time_limit == 60_000


def test_closing_closes_a_redis_brokers_client(app, monkeypatch):
    """Dramatiq's RedisBroker.close closes nothing, and the client is ours"""
    client = MagicMock()
    monkeypatch.setitem(app.extensions, 'jobs_broker', RedisBroker(client=client))

    jobs.close_jobs(app)

    client.close.assert_called_once_with()


@pytest.mark.parametrize(('error', 'line'), [
    (ConnectionError('the mail server is down'), 'with unhandled exception'),
    (PermanentJobFailure('the address does not exist'), 'with expected exception'),
])
def test_the_worker_logs_a_failed_message_by_its_id_alone(make_app, error, line):
    """A real worker logs the message it consumed, arguments and all, through
    the handler run_worker installs: the address must not reach the log"""
    blueprint = Blueprint('things', __name__)

    @job(blueprint)
    def notify(address):
        raise error

    app = make_app(blueprint)
    with app.app_context():
        notify.send('someone@example.com')
    stream = io.StringIO()
    handler = jobs._worker_log_handler(stream)
    log = logging.getLogger('dramatiq')
    level = log.level
    log.addHandler(handler)
    log.setLevel(logging.INFO)
    try:
        run_jobs(app)
    finally:
        log.removeHandler(handler)
        log.setLevel(level)

    [failed] = app.extensions['jobs_broker'].dead_letters
    assert 'someone@example.com' not in stream.getvalue()
    assert f'Failed to process message {failed.message_id} {line}' in stream.getvalue()


class TestRunWorker:
    @pytest.fixture
    def worker(self, make_app, monkeypatch, tmp_path):
        """run_worker on a thread, with the signal handlers it installs kept
        here: a thread may not install its own. Its job records each id it
        starts, waits the seconds it is given, then records the id done."""
        handlers = {}
        monkeypatch.setattr(jobs.signal, 'signal', lambda signum, handler: handlers.setdefault(signum, handler))
        monkeypatch.setattr(jobs, 'READY_FILE', tmp_path / 'worker-ready')
        started, done = [], []
        blueprint = Blueprint('things', __name__)

        @job(blueprint)
        def record(thing_id, seconds=0):
            started.append(thing_id)
            threading.Event().wait(seconds)
            done.append(thing_id)

        app = make_app(blueprint)
        thread = threading.Thread(target=jobs.run_worker, args=(app,))
        thread.start()

        def stop(signum='SIGTERM'):
            number = getattr(jobs.signal, signum)
            handlers[number](number, None)
        yield SimpleNamespace(app=app, record=record, started=started, done=done,
                              stop=stop, thread=thread)
        stop()
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
        assert self.eventually(jobs.READY_FILE.exists)

        with worker.app.app_context():
            worker.record.send(7)

        assert self.eventually(lambda: worker.done == [7])

    @pytest.mark.parametrize('signum', ['SIGTERM', 'SIGINT'])
    def test_a_signal_stops_it(self, worker, signum):
        assert self.eventually(jobs.READY_FILE.exists)

        worker.stop(signum)

        assert self.eventually(lambda: not jobs.READY_FILE.exists())

    def test_lets_a_running_job_finish_when_stopped(self, worker):
        """SIGTERM waits for running jobs (SHUTDOWN_TIMEOUT), so a deploy
        does not cut an email off halfway"""
        assert self.eventually(jobs.READY_FILE.exists)
        with worker.app.app_context():
            worker.record.send(7, 0.5)
        assert self.eventually(lambda: worker.started == [7])

        worker.stop()
        worker.thread.join(timeout=10)

        assert worker.done == [7]
