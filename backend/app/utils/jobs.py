"""Background jobs: slow work a request hands off, run by the worker service.

A request that sends an email must not wait on a mail server, or fail with
it. It queues a job instead (Job.send), which the worker (backend/worker.py)
runs in an app context, retrying it with backoff when it fails.

A feature declares its jobs from its blueprint (`@job(notes_bp)`), as it
registers an export, so the core imports no feature. Messages are JSON and
name a declared job: a message written to Redis can only run a job the code
declares, with JSON arguments, never an arbitrary function.
"""
import functools
import logging
import signal
import sys
import tempfile
import threading
from collections.abc import Callable
from dataclasses import dataclass
from datetime import timedelta
from pathlib import Path
from types import FrameType

from dramatiq import Actor, Broker, Message, Worker
from dramatiq.brokers.redis import RedisBroker
from dramatiq.brokers.stub import StubBroker
from dramatiq.middleware import Retries, TimeLimit
from flask import Blueprint, Flask, current_app
from flask.blueprints import BlueprintSetupState
from redis import Redis, RedisError

from app.utils.log import JsonFormatter
from app.utils.redis_service import REDIS_CLIENT_OPTIONS

# Every queue key starts with it: the Redis ACL in every compose file lets
# the app's and the worker's users reach dramatiq:* (test_redis_acl.py)
QUEUE_NAMESPACE = 'dramatiq'
QUEUE_NAME = 'default'

# A failed job is tried again after 15s, then twice as long each time up to
# an hour: ten retries span about three hours, long enough to outlast a mail
# provider's outage.
MAX_RETRIES = 10
MIN_BACKOFF = timedelta(seconds=15)
MAX_BACKOFF = timedelta(hours=1)
# A job still running after this is stopped and retried; a mail server that
# stops answering is cut off well before by its own timeout (mail.py)
TIME_LIMIT = timedelta(minutes=1)
# A job that used up its retries is kept this long, for a look at what
# failed, then deleted: its arguments may hold an email address
FAILED_JOB_TTL = timedelta(days=1)

# Jobs one worker runs at once. Each waits on the network (a mail server)
# far more than it computes.
WORKER_THREADS = 2
# How long a stopping worker lets running jobs finish. Below the worker
# service's stop_grace_period (docker-compose.yml); a job cut off is
# requeued and runs again.
SHUTDOWN_TIMEOUT = timedelta(seconds=25)
# Written once the worker runs, for the worker service's healthcheck
READY_FILE = Path(tempfile.gettempdir()) / 'worker-ready'

# How often a broker call tidies up after workers that stopped without
# saying so (Dramatiq's default, out of a million calls). Only the worker
# tidies: it calls KEYS, which only the worker's Redis user may run
# (DECISIONS.md). The app's broker never does.
WORKER_MAINTENANCE_CHANCE = 1000


class JobQueueUnavailable(Exception):
    """A job could not be queued because Redis is unavailable (a 503)"""


class PermanentJobFailure(Exception):
    """Raised by a job that must not be retried: trying again would fail
    the same way (a mail server refusing the address)"""


def _millis(delta: timedelta) -> int:
    return int(delta.total_seconds() * 1000)


@dataclass(frozen=True)
class Job:
    """A declared job. Send it from a request; the worker runs it."""
    name: str
    # The function itself, which a test may call directly
    fn: Callable[..., None]

    def send(self, *args: str | int) -> None:
        """Queue the job with these (JSON) arguments"""
        actor: Actor[..., None] = current_app.extensions['jobs'][self.name]
        try:
            actor.send(*args)
        except RedisError as e:
            current_app.logger.exception('Could not queue job %s', self.name)
            raise JobQueueUnavailable() from e


def job(blueprint: Blueprint) -> Callable[[Callable[..., None]], Job]:
    """Declare fn as a job, named after the blueprint and the function.

    The worker runs it in an app context, so it may use db and current_app.
    It takes only what JSON holds: pass ids and addresses, never objects.
    """
    def declare(fn: Callable[..., None]) -> Job:
        declared = Job(name=f'{blueprint.name}.{fn.__name__}', fn=fn)

        def record(state: BlueprintSetupState) -> None:
            # Typed as Flask's base class, which has no app_context
            app = state.app
            assert isinstance(app, Flask)
            app.extensions['jobs'][declared.name] = Actor(
                _in_app_context(app, fn), broker=app.extensions['jobs_broker'],
                actor_name=declared.name, queue_name=QUEUE_NAME, priority=0,
                options={'throws': (PermanentJobFailure,)})

        blueprint.record_once(record)
        return declared

    return declare


def _in_app_context(app: Flask, fn: Callable[..., None]) -> Callable[..., None]:
    @functools.wraps(fn)
    def run(*args: str | int) -> None:
        with app.app_context():
            fn(*args)
    return run


def init_jobs(app: Flask) -> None:
    """Give the app its broker, before its features declare their jobs.

    One broker per app, never Dramatiq's global one, which would connect to
    a Redis on localhost the moment anything asked for it. Unit tests queue
    on an in-memory broker.
    """
    middleware = [
        TimeLimit(time_limit=_millis(TIME_LIMIT)),
        Retries(max_retries=MAX_RETRIES, min_backoff=_millis(MIN_BACKOFF),
                max_backoff=_millis(MAX_BACKOFF)),
    ]
    broker: Broker
    if app.config['USES_SERVICES']:
        client = Redis.from_url(app.config['REDIS_URL'], **REDIS_CLIENT_OPTIONS)
        # Dramatiq's Redis broker has no annotations
        broker = RedisBroker(  # type: ignore[no-untyped-call]
            client=client, namespace=QUEUE_NAMESPACE, middleware=middleware,
            maintenance_chance=0, dead_message_ttl=_millis(FAILED_JOB_TTL))
    else:
        broker = StubBroker(middleware=middleware)
    broker.declare_queue(QUEUE_NAME)
    app.extensions['jobs_broker'] = broker
    app.extensions['jobs'] = {}


class _MessageIdOnly(logging.Filter):
    """Dramatiq logs a failed message with its arguments, which may hold an
    email address: log its id instead"""

    def filter(self, record: logging.LogRecord) -> bool:
        if isinstance(record.args, tuple):
            record.args = tuple(
                arg.message_id if isinstance(arg, Message) else arg for arg in record.args)
        return True


def run_worker(app: Flask) -> None:
    """Run the app's jobs until SIGTERM or SIGINT, then let running jobs
    finish (up to SHUTDOWN_TIMEOUT) and stop"""
    # On a handler, not the logger: a logger's filter skips its children's
    # records, and Dramatiq logs from dramatiq.worker.WorkerThread and the like
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter())
    handler.addFilter(_MessageIdOnly())
    log = logging.getLogger('dramatiq')
    log.addHandler(handler)
    log.setLevel(logging.INFO)

    broker = app.extensions['jobs_broker']
    if isinstance(broker, RedisBroker):
        broker.maintenance_chance = WORKER_MAINTENANCE_CHANCE

    stopping = threading.Event()

    def stop(signum: int, frame: FrameType | None) -> None:
        stopping.set()

    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)

    worker = Worker(broker, worker_threads=WORKER_THREADS)
    worker.start()
    READY_FILE.touch()
    app.logger.info('Worker started: %s', ', '.join(sorted(app.extensions['jobs'])) or 'no jobs')
    stopping.wait()
    app.logger.info('Worker stopping')
    READY_FILE.unlink(missing_ok=True)
    worker.stop(timeout=_millis(SHUTDOWN_TIMEOUT))
    broker.close()
