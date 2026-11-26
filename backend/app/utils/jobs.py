"""Background jobs: slow work a request hands off, run by the worker service.

A request that sends an email must not wait on a mail server, or fail with
it. It queues a job instead (Job.send), which the worker (backend/worker.py)
runs in an app context, retrying it with backoff when it fails.

A feature declares its jobs from its blueprint, as it registers an export,
so the core imports no feature: `@job(<blueprint>)` on the function, or
`job(auth_bp)(send_registration_email)` (auth/routes.py). Messages are JSON and
name a declared job: a message written to Redis can only run a job the code
declares, with JSON arguments, never an arbitrary function. Each is signed
when queued, with a key derived from SECRET_KEY for jobs alone
(utils/keys.py), which nothing else the app shows is made with, and the
worker runs none it cannot verify, so a Redis password alone cannot choose a
job's arguments either: the email change's jobs mint links that move an
account (SignedMessages).

Queue a job before committing when the job is the request's point. Such
a job must not read a row the request writes: the worker reads on its own
connection, which cannot see the row until the commit, so pass the job the
values it needs, or queue after committing. When the write must stand on
its own, queue after committing and catch and log JobQueueUnavailable, as
the password reset does: otherwise a Redis outage answers 503 with the row
already saved, and the user's retry saves it again.
"""
import functools
import hmac
import json
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
from typing import Any, TextIO

from dramatiq import Actor, Broker, Message, Worker
from dramatiq.broker import MessageProxy
from dramatiq.brokers.redis import RedisBroker
from dramatiq.brokers.stub import StubBroker
from dramatiq.middleware import Middleware, Retries, SkipMessage, TimeLimit
from flask import Blueprint, Flask, current_app
from flask.blueprints import BlueprintSetupState
from redis import ConnectionError as RedisConnectionError
from redis import Redis, RedisError
from redis import TimeoutError as RedisTimeoutError

from app.utils.keys import keyed
from app.utils.log import JsonFormatter
from app.utils.redis_service import (
    REDIS_CLIENT_OPTIONS, mark_redis_unreachable, redis_unreachable)

# Every queue key starts with it: the Redis ACL in every compose file lets
# the app's and the worker's users reach dramatiq:* (test_redis_acl.py)
QUEUE_NAMESPACE = 'dramatiq'
QUEUE_NAME = 'default'

# A failed job is tried again after 15-30s (Dramatiq adds jitter), then about
# twice as long each time up to an hour: ten retries span about three hours,
# long enough to outlast a mail provider's outage.
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
# saying so, out of a million calls: one in a hundred, ten times Dramatiq's
# default, so a killed worker's job runs again within a few minutes (about
# 75 s on average) rather than a quarter of an hour. Only the worker tidies:
# it calls KEYS, which only the worker's Redis user may run (DECISIONS.md).
# The app's broker never does.
WORKER_MAINTENANCE_CHANCE = 10_000


class JobQueueUnavailable(Exception):
    """A job could not be queued because Redis is unavailable (a 503)"""


class PermanentJobFailure(Exception):
    """Raised by a job that must not be retried: trying again would fail
    the same way (a mail server refusing the address)"""


def _millis(delta: timedelta) -> int:
    return int(delta.total_seconds() * 1000)


def _signature(secret: str, actor_name: str, args: Any, kwargs: Any) -> str:
    """What a message naming this job with these arguments is signed with:
    an HMAC under the job key, over the arguments as JSON (a message's own
    form), so neither the job nor any argument can be swapped"""
    payload = json.dumps([actor_name, list(args), dict(kwargs or {})],
                         separators=(',', ':'), sort_keys=True)
    return keyed(secret, 'job', payload).hex()


class SignedMessages(Middleware):
    """Runs only messages the app signed (Job.send). One with no signature,
    or a wrong one, was written to Redis by someone else: it is dropped, not
    retried, and logged as job_refused by its id alone, since its arguments
    are a stranger's."""

    def __init__(self, secret: str, log: logging.Logger) -> None:
        self.secret = secret
        self.log = log

    def before_process_message(self, broker: Broker, message: MessageProxy) -> None:
        given = message.options.get('signature')
        expected = _signature(self.secret, message.actor_name, message.args, message.kwargs)
        if not isinstance(given, str) or not hmac.compare_digest(given, expected):
            self.log.warning('job_refused', extra={'fields': {'message_id': message.message_id}})
            raise SkipMessage()


@dataclass(frozen=True)
class Job:
    """A declared job. Send it from a request; the worker runs it."""
    name: str
    # The function itself, which a test may call directly
    fn: Callable[..., None]

    def send(self, *args: str | int) -> None:
        """Queue the job with these (JSON) arguments"""
        actor: Actor[..., None] = current_app.extensions['jobs'][self.name]
        # Redis failed to connect moments ago, here or in the token store:
        # answer at once rather than wait out the outage again
        if redis_unreachable(current_app):
            raise JobQueueUnavailable()
        signature = _signature(current_app.config['JWT_SECRET_KEY'], self.name, args, {})
        try:
            # A message option, which a retry keeps (SignedMessages reads it)
            actor.send_with_options(args=args, signature=signature)
        except RedisError as e:
            if isinstance(e, (RedisConnectionError, RedisTimeoutError)):
                mark_redis_unreachable(current_app)
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
    middleware: list[Middleware] = [
        # First, so nothing else acts on a message no one signed
        SignedMessages(app.config['JWT_SECRET_KEY'], app.logger.getChild('security')),
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


def close_jobs(app: Flask) -> None:
    """Close the app's broker and its Redis connections. Dramatiq's
    RedisBroker.close does nothing, and its client is ours, so it is closed
    here."""
    broker = app.extensions['jobs_broker']
    broker.close()
    if isinstance(broker, RedisBroker):
        broker.client.close()


class _MessageIdOnly(logging.Filter):
    """Dramatiq logs a failed message with its arguments, which may hold an
    email address: log its id instead. Its worker logs the MessageProxy it
    consumed, which is not a Message, so both are replaced."""

    def filter(self, record: logging.LogRecord) -> bool:
        if isinstance(record.args, tuple):
            record.args = tuple(
                arg.message_id if isinstance(arg, (Message, MessageProxy)) else arg
                for arg in record.args)
        return True


def _worker_log_handler(stream: TextIO) -> logging.Handler:
    """The handler the worker logs Dramatiq's lines through: JSON, with each
    message named by its id alone"""
    handler = logging.StreamHandler(stream)
    handler.setFormatter(JsonFormatter())
    handler.addFilter(_MessageIdOnly())
    return handler


def run_worker(app: Flask) -> None:
    """Run the app's jobs until SIGTERM or SIGINT, then let running jobs
    finish (up to SHUTDOWN_TIMEOUT) and stop"""
    # On a handler, not the logger: a logger's filter skips its children's
    # records, and Dramatiq logs from dramatiq.worker.WorkerThread and the like
    log = logging.getLogger('dramatiq')
    log.addHandler(_worker_log_handler(sys.stdout))
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
    close_jobs(app)
