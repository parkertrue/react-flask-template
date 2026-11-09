import os
import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from datetime import timedelta
from email.utils import parseaddr
from urllib.parse import unquote, urlsplit
from sqlalchemy.engine import URL, make_url
from sqlalchemy.exc import ArgumentError

from app.utils.redis_service import RATELIMIT_REDIS_OPTIONS

MIN_SECRET_KEY_LENGTH = 32
PLACEHOLDER_SECRET_KEYS = {'your_secret_key_here'}
# .env.prod.example's values, which must never reach a deployment. The root
# password's never reaches the app: db/init/01-app-user.sh refuses it.
PLACEHOLDER_PASSWORDS = {
    'your_db_password_here', 'your_migration_password_here', 'your_redis_password_here',
    'your_redis_worker_password_here', 'your_smtp_password_here'}
# .env.prod.example's sender, a domain no deployment can send from
PLACEHOLDER_EMAIL_DOMAIN = 'example.com'

# The connect args below are PyMySQL's, so no other driver will do
DATABASE_DRIVER = 'mysql+pymysql'

# The compose files' names for the bundled MySQL and Redis, which the backend
# reaches over a private Docker network. Any other host is outside it, so
# production refuses to reach it without TLS that checks the server's
# certificate and name (docs/deployment.md, External Database or Redis).
BUNDLED_DATABASE_HOST = 'db'
BUNDLED_REDIS_HOST = 'redis'
# URL options that could turn those checks off. PyMySQL checks both once the
# URL names a CA bundle (ssl_ca), and redis-py over rediss:// by default.
DATABASE_TLS_OPTIONS_REFUSED = (
    'ssl_check_hostname', 'ssl_verify_cert', 'ssl_verify_identity', 'ssl_disabled')
REDIS_TLS_OPTIONS_REFUSED = ('ssl_cert_reqs', 'ssl_check_hostname')

# Each database URL's variable, and the one that may hold its password
# instead, so a secrets store can supply the password alone. The migration
# user's comes first: wherever it is set, it wins.
DATABASE_URL_VARIABLES = (('MIGRATION_DATABASE_URL', 'MIGRATION_DATABASE_PASSWORD'),
                          ('DATABASE_URL', 'DATABASE_PASSWORD'))
# What db/init/01-app-user.sh allows: no quoting needed between backticks,
# and `_` the one GRANT wildcard (wait_for_services.py escapes it)
DATABASE_NAME = re.compile(r'[A-Za-z0-9_]+')


def read_database_url(url_var: str, password_var: str) -> URL | None:
    """One database URL, with its password variable applied; None if unset"""
    value = os.getenv(url_var)
    if not value:
        return None
    try:
        url = make_url(value)
    except ArgumentError:
        # Not the value itself: it holds the password
        raise ValueError(f'{url_var} is not a valid URL') from None
    if os.getenv(password_var):
        url = url.set(password=os.getenv(password_var))
    if url.drivername != DATABASE_DRIVER:
        raise ValueError(f'{url_var} must start with {DATABASE_DRIVER}://')
    if not (url.username and url.password and url.host and url.database):
        raise ValueError(
            f'{url_var} must name a user, password, host and database '
            f'(the password may be in {password_var})')
    if not DATABASE_NAME.fullmatch(url.database):
        raise ValueError(f'{url_var} must name a database of letters, digits and _ alone')
    return url


def database_url(migration: bool = True) -> URL | None:
    """The database to connect to, or None if no URL is set.

    The migration user's when MIGRATION_DATABASE_URL is set (only the
    migrate job and the integration suite, which builds its own tables, get
    it) and `migration` allows it, else the app's. A URL object, not a
    string: it prints its password as ***.
    """
    sources = DATABASE_URL_VARIABLES if migration else DATABASE_URL_VARIABLES[1:]
    for url_var, password_var in sources:
        url = read_database_url(url_var, password_var)
        if url:
            return url
    return None


def read_redis_url() -> URL | None:
    """REDIS_URL, with REDIS_PASSWORD as its password if set; None if unset.

    The user is required: the compose files' Redis disables the
    all-powerful "default" user.
    """
    value = os.getenv('REDIS_URL')
    if not value:
        return None
    try:
        url = make_url(value)
    except (ArgumentError, ValueError):
        # Not the value itself: it holds the password. A port that isn't a
        # number is a ValueError
        raise ValueError('REDIS_URL is not a valid URL') from None
    if os.getenv('REDIS_PASSWORD'):
        url = url.set(password=os.getenv('REDIS_PASSWORD'))
    if url.drivername not in ('redis', 'rediss'):
        raise ValueError('REDIS_URL must start with redis:// or rediss:// (TLS)')
    if not all([url.username, url.password, url.host]):
        raise ValueError(
            'REDIS_URL must name a user, password and host '
            '(the password may be in REDIS_PASSWORD)')
    return url


def redis_url() -> str | None:
    """The Redis to connect to, or None if REDIS_URL is unset.

    A string, since Flask-Limiter takes nothing else, so unlike the database
    password this one is readable in app.config.
    """
    url = read_redis_url()
    if url is None:
        return None
    return url.render_as_string(hide_password=False)


# EMAIL_URL's schemes: how the connection to the mail server is secured, and
# the port each uses unless the URL names one. Plain smtp:// is for a local
# mail catcher (Mailpit); production refuses it.
EMAIL_SCHEMES = {'smtps': ('tls', 465), 'smtp+starttls': ('starttls', 587), 'smtp': ('none', 25)}


@dataclass(frozen=True)
class MailServer:
    """Where the worker sends email (app/utils/mail.py)"""
    # 'tls' from the first byte, 'starttls' (required, never optional), or
    # 'none'
    security: str
    host: str
    port: int
    username: str | None
    # Kept out of repr, so a logged config never shows it
    password: str | None = field(default=None, repr=False)


def read_email_url() -> MailServer | None:
    """EMAIL_URL, with EMAIL_PASSWORD as its password if set; None if unset.

    Only the worker sends email, so only its container sets it: the
    backend never holds the mail server's password.
    """
    value = os.getenv('EMAIL_URL')
    if not value:
        return None
    try:
        parts = urlsplit(value)
        port = parts.port
    except ValueError:
        # Not the value itself: it holds the password
        raise ValueError('EMAIL_URL is not a valid URL') from None
    if parts.scheme not in EMAIL_SCHEMES:
        schemes = ', '.join(f'{scheme}://' for scheme in EMAIL_SCHEMES)
        raise ValueError(f'EMAIL_URL must start with one of {schemes}')
    if not parts.hostname:
        raise ValueError('EMAIL_URL must name the mail server')
    if parts.path not in ('', '/') or parts.query or parts.fragment:
        raise ValueError('EMAIL_URL takes a user, password, host and port, nothing else')
    username = unquote(parts.username) if parts.username else None
    password = os.getenv('EMAIL_PASSWORD') or (unquote(parts.password) if parts.password else None)
    if password and not username:
        raise ValueError('EMAIL_URL must name the user its password belongs to')
    security, default_port = EMAIL_SCHEMES[parts.scheme]
    return MailServer(security, parts.hostname, port or default_port, username, password)


def read_email_from() -> str | None:
    """EMAIL_FROM, the sender of every email: an address, with a name
    before it if wanted (App <no-reply@example.com>); None if unset"""
    value = os.getenv('EMAIL_FROM')
    if not value:
        return None
    _, address = parseaddr(value, strict=True)
    if '@' not in address:
        raise ValueError(
            'EMAIL_FROM must be an address, with a name before it if wanted: '
            'App <no-reply@example.com>')
    return value


def read_app_url() -> str | None:
    """APP_URL, where the frontend is served, as scheme://host[:port] with no
    trailing slash; None if unset.

    Emailed links start with it (app/utils/links.py), never with the
    request's Host header. Only the worker sends them, so only it needs it.
    """
    value = os.getenv('APP_URL')
    if not value:
        return None
    try:
        parts = urlsplit(value)
        # Read for its check: a port that isn't a number raises ValueError
        _ = parts.port
    except ValueError:
        raise ValueError('APP_URL is not a valid URL') from None
    if (parts.scheme not in ('http', 'https') or not parts.hostname
            or parts.path not in ('', '/') or parts.query or parts.fragment):
        raise ValueError('APP_URL must be http(s)://<host>[:<port>], nothing else')
    return f'{parts.scheme}://{parts.netloc}'


def refuse_tls_options(url_var: str, query: Mapping[str, object], refused: Iterable[str]) -> None:
    """Fail on any option in a URL's query that could weaken its TLS checks"""
    found = [option for option in refused if option in query]
    if found:
        raise ValueError(
            f"{url_var} may not set {', '.join(found)}: production checks "
            f"the server's certificate and name")


class Config:
    """Base configuration"""

    # Whether the app talks to a real database and Redis, so their settings
    # are required. Only UnitTestConfig opts out: it runs on in-memory SQLite
    # with Redis and rate limiting off.
    USES_SERVICES = True

    def __init__(self) -> None:
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

        self.SQLALCHEMY_DATABASE_URI: URL | str | None = database_url()
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
        query_timeout = db_query_timeout()
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

        # Email, which only the worker sends: unset elsewhere
        self.EMAIL_SERVER = read_email_url()
        self.EMAIL_FROM = read_email_from()
        self.APP_URL = read_app_url()

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
        # Access tokens travel in the Authorization header alone, refresh
        # tokens in an HttpOnly cookie that is only sent to the /api/auth
        # routes, which name that location themselves (locations=['cookies']).
        # Accepting an access token from a cookie too would let a sibling
        # subdomain plant its own in the browser, unprefixed, for every GET
        # sent without the header.
        self.JWT_TOKEN_LOCATION = ['headers']
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

    def __init__(self) -> None:
        super().__init__()
        self.SQLALCHEMY_DATABASE_URI = 'sqlite:///:memory:'
        # MySQL's pool and connection settings mean nothing to SQLite, whose
        # CURRENT_TIMESTAMP is always UTC
        self.SQLALCHEMY_ENGINE_OPTIONS = {'hide_parameters': True}
        self.RATELIMIT_ENABLED = False


class IntegrationConfig(Config):
    """Integration and E2E tests: real database and Redis"""

    def __init__(self) -> None:
        super().__init__()
        self.RATELIMIT_ENABLED = False
        e2e_mode = os.getenv('E2E_MODE', 'false').lower() == 'true'
        # CSRF protection is browser-only; disable it for API integration
        # tests, which have no browser to carry the cookie.
        self.JWT_COOKIE_CSRF_PROTECT = e2e_mode


class ProductionConfig(Config):
    """Production configuration"""

    def __init__(self) -> None:
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

        # Every database URL that is set, not only the one this process
        # connects as: the migrate job also logs in as DATABASE_URL's user,
        # to read its grants (wait_for_services.py)
        for url_var, password_var in DATABASE_URL_VARIABLES:
            database = read_database_url(url_var, password_var)
            if database is None:
                continue
            if database.password in PLACEHOLDER_PASSWORDS:
                raise ValueError('The database password is still the .env.prod.example placeholder')
            if database.host != BUNDLED_DATABASE_HOST:
                if 'ssl_ca' not in database.query:
                    raise ValueError(
                        f'A database host other than {BUNDLED_DATABASE_HOST} needs TLS: add '
                        f'?ssl_ca=<CA bundle path> to {url_var}')
                refuse_tls_options(url_var, database.query, DATABASE_TLS_OPTIONS_REFUSED)

        redis = read_redis_url()
        # Config.__init__ has already refused an unset REDIS_URL
        assert redis is not None
        if redis.password in PLACEHOLDER_PASSWORDS:
            raise ValueError('The Redis password is still the .env.prod.example placeholder')
        if redis.host != BUNDLED_REDIS_HOST:
            if redis.drivername != 'rediss':
                raise ValueError(
                    f'A Redis host other than {BUNDLED_REDIS_HOST} needs TLS: '
                    f'start REDIS_URL with rediss://')
            refuse_tls_options('REDIS_URL', redis.query, REDIS_TLS_OPTIONS_REFUSED)

        # Set in the worker's container alone. The mail server is always
        # outside the host, and its password and every email's links cross
        # the internet, so the connection must be TLS, which smtplib checks
        # against the system's CAs (mail.py).
        if self.EMAIL_SERVER is not None:
            if self.EMAIL_SERVER.password in PLACEHOLDER_PASSWORDS:
                raise ValueError('The mail server password is still the .env.prod.example placeholder')
            if self.EMAIL_SERVER.security == 'none':
                raise ValueError(
                    'EMAIL_URL needs TLS in production: start it with smtps:// or smtp+starttls://')
        # The worker's links: the first name nginx serves, unless APP_URL
        # says otherwise (a platform's container has no SERVER_NAME)
        server_names = os.getenv('SERVER_NAME', '').split()
        if self.APP_URL is None and server_names:
            self.APP_URL = f'https://{server_names[0]}'
        if self.APP_URL is not None and not self.APP_URL.startswith('https://'):
            raise ValueError('APP_URL must start with https:// in production')
        if self.EMAIL_FROM is not None:
            _, sender = parseaddr(self.EMAIL_FROM, strict=True)
            if sender.rpartition('@')[2].lower() == PLACEHOLDER_EMAIL_DOMAIN:
                raise ValueError('EMAIL_FROM is still the .env.prod.example placeholder')


def trusted_proxy_count() -> int:
    """How many proxies in production write X-Forwarded-For, 1 by default.

    nginx is the one hop in front of the backend wherever it runs, even
    behind a load balancer: it takes the client's address from the
    balancer's header itself (NGINX_TRUSTED_PROXIES) and forwards that alone.
    A deployment without nginx counts the proxies that append to the header:
    1 for a load balancer, 2 with a CDN before it. Too low, and every user
    shares the proxy's address and one rate-limit bucket; too high, and a
    client picks its own address.
    """
    value = os.getenv('TRUSTED_PROXY_COUNT', '1')
    if not (value.isascii() and value.isdigit()):
        raise ValueError(f'TRUSTED_PROXY_COUNT must be a whole number, 0 or more. Got: {value!r}')
    return int(value)


def db_query_timeout() -> int:
    """Seconds each MySQL query may take, 15 by default; 0 for no limit."""
    value = os.getenv('DB_QUERY_TIMEOUT', '15')
    if not (value.isascii() and value.isdigit()):
        raise ValueError(
            f'DB_QUERY_TIMEOUT must be a whole number of seconds, 0 for none. Got: {value!r}')
    return int(value)


def get_config() -> Config:
    """Get configuration based on environment

    APP_ENV is the only switch: no other variable (E2E_MODE included) may
    swap a config class, or one env var could weaken production. Unset means
    production, the strictest class.
    """
    app_env = os.getenv('APP_ENV', 'production')

    config_map: dict[str, type[Config]] = {
        'development': DevelopmentConfig,
        'unit': UnitTestConfig,
        'integration': IntegrationConfig,
        'production': ProductionConfig,
    }

    if app_env not in config_map:
        raise ValueError(
            f'APP_ENV must be one of: {", ".join(config_map)}. Got: {app_env}')

    return config_map[app_env]()
