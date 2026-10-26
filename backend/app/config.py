import os
from datetime import timedelta
from urllib.parse import parse_qs, quote, unquote, urlsplit

from sqlalchemy.engine import URL, make_url
from sqlalchemy.exc import ArgumentError

from app.utils.redis_service import RATELIMIT_REDIS_OPTIONS

MIN_SECRET_KEY_LENGTH = 32
PLACEHOLDER_SECRET_KEYS = {'your_secret_key_here'}
# .env.prod.example's values, which must never reach a deployment. The root
# password's never reaches the app: db/init/01-app-user.sh refuses it.
PLACEHOLDER_PASSWORDS = {
    'your_db_password_here', 'your_migration_password_here', 'your_redis_password_here'}

# The connect args below are PyMySQL's, so no other driver will do
DATABASE_DRIVER = 'mysql+pymysql'

# The compose files' names for the bundled MySQL and Redis, which the backend
# reaches over a private Docker network. Any other host is outside it, so
# production refuses to reach it without TLS that checks the server's
# certificate and name (README, External Database or Redis).
BUNDLED_DATABASE_HOST = 'db'
BUNDLED_REDIS_HOST = 'redis'
# URL options that could turn those checks off. PyMySQL checks both once the
# URL names a CA bundle (ssl_ca), and redis-py over rediss:// by default.
DATABASE_TLS_OPTIONS_REFUSED = (
    'ssl_check_hostname', 'ssl_verify_cert', 'ssl_verify_identity', 'ssl_disabled')
REDIS_TLS_OPTIONS_REFUSED = ('ssl_cert_reqs', 'ssl_check_hostname')


def database_url(migration=True) -> URL | None:
    """The database to connect to, or None if no URL is set.

    The migration user's when MIGRATION_DATABASE_URL is set (only the
    migrate job and the integration suite, which builds its own tables, get
    it) and `migration` allows it, else the app's. Each URL's password may
    come from a variable of its own instead, so a secrets store can supply
    the password alone. A URL object, not a string: it prints its password
    as ***.
    """
    sources = (('MIGRATION_DATABASE_URL', 'MIGRATION_DATABASE_PASSWORD'),
               ('DATABASE_URL', 'DATABASE_PASSWORD'))
    for url_var, password_var in sources if migration else sources[1:]:
        value = os.getenv(url_var)
        if not value:
            continue
        try:
            url = make_url(value)
        except ArgumentError:
            # Not the value itself: it holds the password
            raise ValueError(f'{url_var} is not a valid URL') from None
        if os.getenv(password_var):
            url = url.set(password=os.getenv(password_var))
        if url.drivername != DATABASE_DRIVER:
            raise ValueError(f'{url_var} must start with {DATABASE_DRIVER}://')
        if not all([url.username, url.password, url.host, url.database]):
            raise ValueError(
                f'{url_var} must name a user, password, host and database '
                f'(the password may be in {password_var})')
        return url
    return None


def redis_url() -> str | None:
    """REDIS_URL, with REDIS_PASSWORD as its password if set; None if unset.

    A string, since Flask-Limiter takes nothing else, so unlike the database
    password this one is readable in app.config. The user is required: the
    compose files' Redis disables the all-powerful "default" user.
    """
    value = os.getenv('REDIS_URL')
    if not value:
        return None
    try:
        parts = urlsplit(value)
        parts.port  # raises on a port that isn't a number
    except ValueError:
        raise ValueError('REDIS_URL is not a valid URL') from None
    if parts.scheme not in ('redis', 'rediss'):
        raise ValueError('REDIS_URL must start with redis:// or rediss:// (TLS)')
    password = os.getenv('REDIS_PASSWORD') or unquote(parts.password or '')
    if not (parts.username and password and parts.hostname):
        raise ValueError(
            'REDIS_URL must name a user, password and host '
            '(the password may be in REDIS_PASSWORD)')
    host = parts.netloc.rpartition('@')[2]
    return parts._replace(
        netloc=f"{parts.username}:{quote(password, safe='')}@{host}").geturl()


def refuse_tls_options(service, query, refused):
    """Fail on any option in a URL's query that could weaken its TLS checks"""
    found = [option for option in refused if option in query]
    if found:
        raise ValueError(
            f"The {service} URL may not set {', '.join(found)}: production checks "
            f"the server's certificate and name")


class Config:
    """Base configuration"""

    # Whether the app talks to a real database and Redis, so their settings
    # are required. Only UnitTestConfig opts out: it runs on in-memory SQLite
    # with Redis and rate limiting off.
    USES_SERVICES = True

    def __init__(self):
        # Parse as a string: os.getenv always returns str, and the bare string
        # "0" is truthy, which would silently enable debug mode wherever
        # FLASK_DEBUG=0 was set.
        self.FLASK_DEBUG = os.getenv('FLASK_DEBUG', '0').lower() in ('1', 'true')

        # Every request body is a small JSON object; refuse anything larger
        # than this before parsing it. nginx enforces the same cap.
        self.MAX_CONTENT_LENGTH = 16 * 1024

        # Password hashes each gunicorn worker may compute at once, out of its
        # threads (see backend/Dockerfile). The rest stay free for other
        # requests during a burst of logins. A login that waits longer than
        # the timeout for a slot gets a 503.
        self.PASSWORD_HASH_CONCURRENCY = 2
        self.PASSWORD_HASH_WAIT_SECONDS = 5

        self.SQLALCHEMY_DATABASE_URI = database_url()
        if self.SQLALCHEMY_DATABASE_URI is None and self.USES_SERVICES:
            raise ValueError('Missing required environment variable: DATABASE_URL')

        connect_args = {
            # Every timestamp is UTC, and the API says so. NOW() and
            # CURRENT_TIMESTAMP follow the connection's time zone, which would
            # otherwise be whatever the server is set to.
            'init_command': "SET time_zone = '+00:00'",
            'connect_timeout': 5,
        }
        # PyMySQL waits on a query forever by default, so a hung database (a
        # full disk, a lock) would hold a request thread long after nginx gave
        # up at 60s, until every thread is stuck. The migrate service sets 0
        # (no limit): a migration on a big table may legitimately run longer.
        query_timeout = int(os.getenv('DB_QUERY_TIMEOUT', '15'))
        if query_timeout:
            connect_args.update(read_timeout=query_timeout, write_timeout=query_timeout)
        self.SQLALCHEMY_ENGINE_OPTIONS = {
            # MySQL closes connections idle past wait_timeout (8h by default),
            # and any restart or network blip drops them all; without a ping,
            # the next request on each dead pooled connection fails with a
            # 500. Recycling well before wait_timeout keeps the ping from
            # finding many dead ones.
            'pool_pre_ping': True,
            'pool_recycle': 1800,
            'connect_args': connect_args,
            # A failed statement's exception text, which the error handlers
            # log, would otherwise carry its values: password hashes, emails
            # and user text.
            'hide_parameters': True,
        }

        # Redis configuration
        self.REDIS_URL = redis_url()
        if self.REDIS_URL is None and self.USES_SERVICES:
            raise ValueError('Missing required environment variable: REDIS_URL')
        # Per worker: well above its 4 threads, so no request waits on the pool
        self.REDIS_MAX_CONNECTIONS = 50

        # Rate Limiter configuration
        self.RATELIMIT_ENABLED = True
        self.RATELIMIT_STORAGE_URI = self.REDIS_URL
        self.RATELIMIT_STORAGE_OPTIONS = RATELIMIT_REDIS_OPTIONS
        # If Redis is unreachable, count in each worker's memory until it is
        # back, rather than failing every rate-limited request with a 500.
        self.RATELIMIT_IN_MEMORY_FALLBACK_ENABLED = True
        # A failed login is counted after the response is built, where the
        # fallback doesn't reach: a Redis that refuses the write (full) would
        # turn the 401 into a 500. Log it and answer anyway. Limit checks
        # still try the fallback first, so it changes nothing there.
        self.RATELIMIT_SWALLOW_ERRORS = True

        # Number of reverse proxies in front of Flask whose X-Forwarded-*
        # headers are trusted. 0 means REMOTE_ADDR is the client.
        self.TRUSTED_PROXY_COUNT = 0

        # JWT configuration
        self.JWT_SECRET_KEY = os.getenv('SECRET_KEY', '')
        self.JWT_ACCESS_TOKEN_EXPIRES = timedelta(minutes=15)
        # A session lasts at most JWT_REFRESH_TOKEN_EXPIRES from login, and
        # ends sooner once it goes SESSION_IDLE_TIMEOUT without a refresh:
        # each refresh token expires at the earlier of the two
        self.JWT_REFRESH_TOKEN_EXPIRES = timedelta(days=30)
        self.SESSION_IDLE_TIMEOUT = timedelta(days=7)
        # Access tokens travel in the Authorization header, refresh tokens in
        # an HttpOnly cookie (always, in Flask-JWT-Extended) that is only sent
        # to the /api/auth routes.
        self.JWT_TOKEN_LOCATION = ['headers', 'cookies']
        # __Secure- makes browsers refuse the cookie unless it is Secure and
        # set over HTTPS, so a sibling subdomain or plain-HTTP page can't
        # plant one under this name. (__Host- would also forbid the path.)
        # Browsers count http://localhost as secure, so dev works too.
        self.JWT_REFRESH_COOKIE_NAME = '__Secure-refresh_token'
        self.JWT_COOKIE_SECURE = True
        self.JWT_REFRESH_COOKIE_PATH = '/api/auth'
        self.JWT_COOKIE_SAMESITE = 'Lax'
        # Double-submit CSRF for the refresh cookie. The client gets the value
        # in the login/refresh response body, so no readable CSRF cookie is set.
        self.JWT_COOKIE_CSRF_PROTECT = True
        self.JWT_CSRF_IN_COOKIES = False
        self.JWT_REFRESH_CSRF_HEADER_NAME = 'X-CSRF-REFRESH-TOKEN'

        if not self.JWT_SECRET_KEY:
            raise ValueError('SECRET_KEY environment variable not set')


class DevelopmentConfig(Config):
    """Development configuration"""


class UnitTestConfig(Config):
    """Unit tests: in-memory SQLite, no Redis, no rate limiting"""
    USES_SERVICES = False

    def __init__(self):
        super().__init__()
        self.SQLALCHEMY_DATABASE_URI = 'sqlite:///:memory:'
        # MySQL's pool and connection settings mean nothing to SQLite, whose
        # CURRENT_TIMESTAMP is always UTC
        self.SQLALCHEMY_ENGINE_OPTIONS = {'hide_parameters': True}
        self.RATELIMIT_ENABLED = False


class IntegrationConfig(Config):
    """Integration and E2E tests: real database and Redis"""

    def __init__(self):
        super().__init__()
        self.RATELIMIT_ENABLED = False
        e2e_mode = os.getenv('E2E_MODE', 'false').lower() == 'true'
        # CSRF protection is browser-only; disable it for API integration
        # tests, which have no browser to carry the cookie.
        self.JWT_COOKIE_CSRF_PROTECT = e2e_mode


class ProductionConfig(Config):
    """Production configuration"""

    def __init__(self):
        super().__init__()
        self.FLASK_DEBUG = False
        self.TRUSTED_PROXY_COUNT = trusted_proxy_count()

        # Anyone who knows the template's placeholder can forge JWTs, so a
        # weak key must stop the deploy rather than boot quietly.
        if (len(self.JWT_SECRET_KEY) < MIN_SECRET_KEY_LENGTH
                or self.JWT_SECRET_KEY in PLACEHOLDER_SECRET_KEYS):
            raise ValueError(
                f'SECRET_KEY must be a random value of at least '
                f'{MIN_SECRET_KEY_LENGTH} characters in production')

        passwords = {
            'The database password': self.SQLALCHEMY_DATABASE_URI.password,
            'The Redis password': unquote(urlsplit(self.REDIS_URL).password),
        }
        for name, password in passwords.items():
            if password in PLACEHOLDER_PASSWORDS:
                raise ValueError(f'{name} is still the .env.prod.example placeholder')

        database = self.SQLALCHEMY_DATABASE_URI
        if database.host != BUNDLED_DATABASE_HOST:
            if 'ssl_ca' not in database.query:
                raise ValueError(
                    f'A database host other than {BUNDLED_DATABASE_HOST} needs TLS: add '
                    f'?ssl_ca=<CA bundle path> to its URL')
            refuse_tls_options('database', database.query, DATABASE_TLS_OPTIONS_REFUSED)
        redis = urlsplit(self.REDIS_URL)
        if redis.hostname != BUNDLED_REDIS_HOST:
            if redis.scheme != 'rediss':
                raise ValueError(
                    f'A Redis host other than {BUNDLED_REDIS_HOST} needs TLS: '
                    f'start REDIS_URL with rediss://')
            refuse_tls_options('Redis', parse_qs(redis.query), REDIS_TLS_OPTIONS_REFUSED)


def trusted_proxy_count():
    """How many proxies in production write X-Forwarded-For, 1 by default.

    nginx is the one hop in front of the backend wherever it runs, even
    behind a load balancer: it takes the client's address from the
    balancer's header itself (NGINX_TRUSTED_PROXIES) and forwards that alone.
    A deployment without nginx counts the proxies that append to the header:
    1 for a load balancer, 2 with a CDN before it. Too
    low, and every user shares the proxy's address and one rate-limit
    bucket; too high, and a client picks its own address.
    """
    value = os.getenv('TRUSTED_PROXY_COUNT', '1')
    if not (value.isascii() and value.isdigit()):
        raise ValueError(f'TRUSTED_PROXY_COUNT must be a whole number, 0 or more. Got: {value!r}')
    return int(value)


def get_config():
    """Get configuration based on environment

    APP_ENV is the only switch: no other variable (E2E_MODE included) may
    swap a config class, or one env var could weaken production. Unset means
    production, the strictest class.
    """
    app_env = os.getenv('APP_ENV', 'production')

    config_map = {
        'development': DevelopmentConfig,
        'unit': UnitTestConfig,
        'integration': IntegrationConfig,
        'production': ProductionConfig,
    }

    if app_env not in config_map:
        raise ValueError(
            f'APP_ENV must be one of: {", ".join(config_map)}. Got: {app_env}')

    return config_map[app_env]()
