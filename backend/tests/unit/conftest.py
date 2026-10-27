import json

import pytest

from app.utils.log import JsonFormatter
from tests.conftest import FakeRedisService


@pytest.fixture(autouse=True)
def fake_redis(request):
    """Every test of the unit app gets an in-memory Redis token store.

    UnitTestConfig runs without Redis, but the app treats a missing store as
    an outage (login and refresh answer 503), so tests
    sign in through the same path production does. Request `no_redis` to test
    the outage itself.
    """
    if 'app' not in request.fixturenames:
        yield None
        return
    app = request.getfixturevalue('app')
    fake = FakeRedisService()
    app.extensions['redis_service'] = fake
    yield fake
    app.extensions['redis_service'] = None


@pytest.fixture
def no_redis(app, fake_redis):
    """The unit app with Redis unreachable"""
    app.extensions['redis_service'] = None


@pytest.fixture
def logged(caplog):
    """The app's log so far, each record as the JSON object production writes"""
    formatter = JsonFormatter()
    return lambda: [json.loads(formatter.format(record)) for record in caplog.records]


@pytest.fixture
def security_events(logged):
    """The security events logged so far, without their time and level"""
    def events():
        return [{k: v for k, v in line.items() if k not in ('time', 'level', 'logger')}
                for line in logged() if line['logger'] == 'app.security']
    return events
