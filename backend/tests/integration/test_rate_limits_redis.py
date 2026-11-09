"""Rate limits counted in the real Redis, under the app's ACL user.

The ACL lets the app touch only refresh_tokens:* and LIMITS:* keys. If the
limiter wrote anywhere else, Redis would refuse it and the limiter would fall
back to counting in each worker's memory: limits would still seem to work in
a quick test, but every worker would count separately.
"""
import pytest

import app as app_module
from app import create_app, limiter
from app.config import IntegrationConfig
from tests.conftest import close_app

LOGIN = {'email': 'nobody@example.com', 'password': 'WrongPassword123'}


@pytest.fixture
def limited_client(integration_db, integration_redis, monkeypatch):
    """A client of an app like integration_app, with rate limiting on.

    init_app changes the module-level limiter for every app, so its state is
    put back afterwards, as in the unit tests.
    """
    saved = dict(vars(limiter))
    config = IntegrationConfig()
    config.RATELIMIT_ENABLED = True
    monkeypatch.setattr(app_module, 'get_config', lambda: config)

    app = create_app()
    yield app.test_client()

    close_app(app)
    # And the limiter's own Redis client, which init_app opened
    limiter.storage.storage.close()
    vars(limiter).clear()
    vars(limiter).update(saved)


def test_limits_are_counted_in_redis(limited_client, integration_redis):
    statuses = [limited_client.post('/api/auth/login', json=LOGIN).status_code
                for _ in range(6)]

    assert statuses == [401] * 5 + [429]
    # Proof the counts went to Redis rather than the in-memory fallback
    assert list(integration_redis.get_client().scan_iter('LIMITS:*'))
