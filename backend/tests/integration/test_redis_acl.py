"""What the app's Redis ACL user may not do, against the real server.

The compose files give the user its own key patterns, minus @dangerous and
the categories of every module the redis image loads, which @dangerous does
not cover. Each forbidden command uses a key the user may otherwise touch, so
only the command's category can be what refuses it.
"""
import pytest
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


def test_the_app_user_may_use_its_own_keys(integration_redis):
    """The control: the refusals above are the ACL's, not a failed login"""
    client = integration_redis.get_client()

    assert client.set('refresh_tokens:acl-plain', '1') is True
