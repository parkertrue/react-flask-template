"""What the app's and the worker's Redis ACL users may not do, against the
real server.

The compose files give each user its own key patterns, minus @dangerous and
the categories of every module the redis image loads, which @dangerous does
not cover; the worker's user may run KEYS, which the job queue's upkeep
calls. Each forbidden command uses a key the user may otherwise touch, so
only the command's category can be what refuses it.
"""
import os

import pytest
import redis
from redis.exceptions import NoPermissionError

FORBIDDEN = [
    # @dangerous
    ('FLUSHALL',),
    ('CONFIG', 'GET', 'maxmemory'),
    ('KEYS', '*'),
    # The modules: search, JSON, time series and the probabilistic types
    ('FT.CONFIG', 'SET', 'TIMEOUT', '1'),
    ('FT.CREATE', 'refresh_tokens:acl-index', 'ON', 'HASH',
     'PREFIX', '1', 'refresh_tokens:', 'SCHEMA', 'jti', 'TEXT'),
    ('JSON.SET', 'refresh_tokens:acl-json', '$', '1'),
    ('TS.CREATE', 'refresh_tokens:acl-series'),
    ('BF.ADD', 'refresh_tokens:acl-bloom', 'x'),
    ('CF.ADD', 'refresh_tokens:acl-cuckoo', 'x'),
    ('CMS.INITBYDIM', 'refresh_tokens:acl-cms', '10', '5'),
    ('TOPK.RESERVE', 'refresh_tokens:acl-topk', '10'),
    ('TDIGEST.CREATE', 'refresh_tokens:acl-tdigest'),
]


@pytest.mark.parametrize('command', FORBIDDEN, ids=lambda command: command[0])
def test_the_app_user_may_not_run(integration_redis, command):
    with pytest.raises(NoPermissionError):
        integration_redis.get_client().execute_command(*command)


@pytest.mark.parametrize('key', ['refresh_tokens:acl-plain', 'LIMITS:acl-plain', 'dramatiq:acl-plain'])
def test_the_app_user_may_use_its_own_keys(integration_redis, key):
    """The control: the refusals above are the ACL's, not a failed login.
    dramatiq:* is the job queue, where the app puts jobs."""
    client = integration_redis.get_client()

    assert client.set(key, '1') is True


@pytest.fixture
def worker_redis(integration_redis):
    """A client logged in as the worker's user"""
    client = redis.Redis.from_url(os.environ['REDIS_WORKER_URL'])
    yield client
    client.close()


def on_queue_keys(command):
    """The command, its key moved into the job queue's"""
    return tuple(arg.replace('refresh_tokens:', 'dramatiq:') for arg in command)


@pytest.mark.parametrize('command', [c for c in FORBIDDEN if c[0] != 'KEYS'],
                         ids=lambda command: command[0])
def test_the_worker_user_may_not_run(worker_redis, command):
    with pytest.raises(NoPermissionError):
        worker_redis.execute_command(*on_queue_keys(command))


def test_the_worker_user_may_run_keys(worker_redis):
    """The one dangerous command it holds, for the job queue's upkeep
    (app/utils/jobs.py)"""
    worker_redis.set('dramatiq:acl-plain', '1')

    assert worker_redis.keys('dramatiq:acl-*') == [b'dramatiq:acl-plain']


@pytest.mark.parametrize('key', ['refresh_tokens:acl-plain', 'LIMITS:acl-plain'])
def test_the_worker_user_may_not_touch_the_apps_keys(worker_redis, key):
    """A stolen worker password reaches the job queue, not the sessions or
    the rate limits"""
    with pytest.raises(NoPermissionError):
        worker_redis.get(key)
