import os
import pytest
import sqlite3
from datetime import timedelta
from flask_jwt_extended import create_access_token
from sqlalchemy import event
from sqlalchemy.engine import Engine

from app import create_app, db as _db
from app.auth.models import User

# Every config requires SECRET_KEY, including the ones tests build directly.
# Integration runs get theirs from .env.test, which this does not override.
os.environ.setdefault('SECRET_KEY', 'test-secret-key-0123456789abcdef')


# ============================================================================
# UNIT TEST FIXTURES (Fast, SQLite in-memory, no Redis)
# ============================================================================

@pytest.fixture(scope='session')
def app():
    """The unit app: UnitTestConfig, so in-memory SQLite whatever DATABASE_URL says, no Redis and no rate limiting."""
    os.environ['APP_ENV'] = 'unit'

    app = create_app()

    with app.app_context():
        yield app
        # Close the in-memory database's connection rather than leave it to
        # the garbage collector, which Python warns about
        _db.engine.dispose()


@event.listens_for(Engine, 'connect')
def enable_sqlite_foreign_keys(dbapi_conn, connection_record):
    """SQLite ignores foreign keys (and ON DELETE CASCADE) unless asked.

    Registered once, here: inside a fixture, every test would add another
    listener on SQLAlchemy's global Engine class.
    """
    if isinstance(dbapi_conn, sqlite3.Connection):
        cursor = dbapi_conn.cursor()
        cursor.execute('PRAGMA foreign_keys=ON')
        cursor.close()


@pytest.fixture(scope='function')
def db(app):
    """Unit test database - SQLite in-memory"""
    with app.app_context():
        _db.create_all()
        yield _db
        _db.session.remove()
        _db.drop_all()


@pytest.fixture(scope='function')
def client(app, db):
    """Unit test client"""
    return app.test_client()


class FakeRedisService:
    """In-memory stand-in for RedisService's refresh-token methods."""

    def __init__(self):
        self.tokens = set()  # {(user_id, jti)}
        self.ttls = {}  # {jti: the ttl_seconds it was recorded with}

    def store_refresh_token(self, user_id, jti, ttl_seconds):
        self.tokens.add((user_id, jti))
        self.ttls[jti] = ttl_seconds
        return True

    def rotate_refresh_token(self, user_id, old_jti, new_jti, ttl_seconds):
        if (user_id, old_jti) not in self.tokens:
            return False
        self.tokens.discard((user_id, old_jti))
        self.tokens.add((user_id, new_jti))
        self.ttls[new_jti] = ttl_seconds
        return True

    def is_token_valid(self, user_id, jti):
        return (user_id, jti) in self.tokens

    def revoke_token(self, user_id, jti):
        self.tokens.discard((user_id, jti))

    def revoke_all_user_tokens(self, user_id):
        mine = {t for t in self.tokens if t[0] == user_id}
        self.tokens -= mine
        return len(mine)


# ============================================================================
# INTEGRATION TEST FIXTURES (Real MySQL + Redis from docker-compose.test.yml)
# ============================================================================

@pytest.fixture(scope='session')
def integration_app():
    """Integration test app - uses real MySQL + Redis

    Uses IntegrationConfig which:
    - Reads MySQL/Redis connection details from environment
    - Connects to test services on ports 3307 (MySQL) and 6380 (Redis), to
      MySQL as the migration user, since integration_db creates the tables
    - Disables rate limiting (test_rate_limits_redis.py turns it back on)

    Environment variables are loaded by run_tests.sh from .env.test. If running
    pytest directly, ensure .env.test is loaded first.
    """
    os.environ['APP_ENV'] = 'integration'

    required_vars = ['MIGRATION_DATABASE_URL', 'DATABASE_URL', 'REDIS_URL']
    missing = [v for v in required_vars if v not in os.environ]
    if missing:
        raise RuntimeError(
            f'Missing required environment variables: {missing}\n'
            f'Make sure to run tests with ./run_tests.sh which loads .env.test'
        )

    app = create_app()

    with app.app_context():
        # No retry: `up -d --wait` (run_tests.sh and CI) already waits for the
        # services' healthchecks, so a failure here means they are not running
        try:
            with _db.engine.connect():
                pass
        except Exception as e:
            raise RuntimeError(
                f"Test database not reachable: {e}\n"
                f"Run ./run_tests.sh integration, or 'docker compose "
                f"--env-file .env.test -f docker-compose.test.yml up -d --wait'."
            ) from e

        # IntegrationConfig enables Redis, so a missing service means it failed
        # to connect in create_app(): fail once, here, rather than in every
        # Redis-backed test.
        if app.extensions['redis_service'] is None:
            raise RuntimeError(
                'Redis failed to initialize; see the log above. Make sure '
                'docker-compose.test.yml services are healthy.')

        yield app


@pytest.fixture(scope='function')
def integration_db(integration_app):
    """Integration test database - real MySQL

    Creates a fresh schema before each test and drops it after, so tests stay
    isolated from one another.
    """
    with integration_app.app_context():
        _db.create_all()
        yield _db
        _db.session.remove()
        _db.drop_all()


@pytest.fixture(scope='function')
def integration_client(integration_app, integration_db):
    """Integration test client"""
    return integration_app.test_client()


@pytest.fixture(scope='function')
def integration_redis(integration_app):
    """Integration test Redis - real Redis

    Deletes the app's keys after each test to keep tests isolated. FLUSHDB
    is not an option: the app's ACL user may not run it.
    """
    with integration_app.app_context():
        redis_service = integration_app.extensions['redis_service']
        yield redis_service
        client = redis_service.get_client()
        for pattern in ('refresh_tokens:*', 'LIMITS:*'):
            keys = list(client.scan_iter(pattern))
            if keys:
                client.delete(*keys)


@pytest.fixture
def integration_user(integration_db):
    """Sample user for integration tests"""
    user = User(email='integration@test.com')
    user.set_password('TestPassword123')
    integration_db.session.add(user)
    integration_db.session.commit()
    integration_db.session.refresh(user)
    return user


# ============================================================================
# UNIT FIXTURES - users and tokens (on the unit db)
# ============================================================================

@pytest.fixture
def sample_user(db):
    """Create a sample user for testing."""
    user = User(email='test@example.com')
    user.set_password('TestPassword123')
    db.session.add(user)
    db.session.commit()
    db.session.refresh(user)
    return user


@pytest.fixture
def second_user(db):
    """Create a second user for authorization tests."""
    user = User(email='other@example.com')
    user.set_password('OtherPassword123')
    db.session.add(user)
    db.session.commit()
    db.session.refresh(user)
    return user


@pytest.fixture
def auth_token(app, sample_user):
    """Generate a valid JWT token for the sample user."""
    with app.app_context():
        token = create_access_token(identity=str(sample_user.id))
        return token


@pytest.fixture
def second_auth_token(app, second_user):
    """Generate a valid JWT token for the second user."""
    with app.app_context():
        token = create_access_token(identity=str(second_user.id))
        return token


@pytest.fixture
def expired_token(app, sample_user):
    """Generate an expired JWT token."""
    with app.app_context():
        token = create_access_token(
            identity=str(sample_user.id),
            expires_delta=timedelta(seconds=-1)
        )
        return token


@pytest.fixture
def auth_headers(auth_token):
    """Generate authorization headers with valid token."""
    return {
        'Authorization': f'Bearer {auth_token}',
        'Content-Type': 'application/json'
    }


@pytest.fixture
def second_auth_headers(second_auth_token):
    """Generate authorization headers for second user."""
    return {
        'Authorization': f'Bearer {second_auth_token}',
        'Content-Type': 'application/json'
    }
