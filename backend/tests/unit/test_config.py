import pytest
from datetime import timedelta

from redis.connection import parse_url
from sqlalchemy.engine import make_url

from app.config import (
    Config,
    database_url,
    DevelopmentConfig,
    UnitTestConfig,
    IntegrationConfig,
    ProductionConfig,
    get_config
)

STRONG_SECRET = 'x' * 32

# The bundled services' hosts, which production reaches without TLS
SERVICE_ENV = {
    'DATABASE_URL': 'mysql+pymysql://user:dbpass@db:3306/db',
    'REDIS_URL': 'redis://app:redispass@redis:6379/0',
}

# Read by app/config.py, but not set by SERVICE_ENV
OPTIONAL_VARS = (
    'MIGRATION_DATABASE_URL', 'DATABASE_PASSWORD', 'MIGRATION_DATABASE_PASSWORD',
    'REDIS_PASSWORD', 'FLASK_DEBUG', 'E2E_MODE', 'TRUSTED_PROXY_COUNT')


@pytest.fixture(autouse=True)
def isolate_config_tests(monkeypatch):
    """Give every test the same environment, whatever the shell has loaded.

    Optional vars are cleared so tests see the documented defaults, and the
    URLs the service-backed configs require are set to placeholders.
    Tests that need other values set or delete them with monkeypatch.
    """
    for var in OPTIONAL_VARS:
        monkeypatch.delenv(var, raising=False)
    for var, value in SERVICE_ENV.items():
        monkeypatch.setenv(var, value)
    monkeypatch.setenv('SECRET_KEY', 'testsecret')


class TestConfigClasses:
    """Test Config class attributes"""

    def test_config_class_reads_env_vars(self):
        config = Config()

        url = config.SQLALCHEMY_DATABASE_URI
        assert (url.username, url.password, url.host, url.port, url.database) == (
            'user', 'dbpass', 'db', 3306, 'db')
        assert config.REDIS_URL == 'redis://app:redispass@redis:6379/0'
        assert config.RATELIMIT_STORAGE_URI == config.REDIS_URL
        assert config.JWT_SECRET_KEY == 'testsecret'

    def test_passwords_sit_only_inside_the_urls(self):
        """The database URL masks its password when printed; Flask-Limiter
        takes only a string, so the Redis password is readable in its URLs"""
        config = Config()

        holding = {name: value for name, value in vars(config).items()
                   if 'dbpass' in str(value) or 'redispass' in str(value)}
        assert sorted(holding) == ['RATELIMIT_STORAGE_URI', 'REDIS_URL']

    def test_development_config_attributes(self):
        """DevelopmentConfig should have correct attributes"""
        config = DevelopmentConfig()

        assert config.USES_SERVICES is True
        assert config.RATELIMIT_ENABLED is True

    @pytest.mark.parametrize('value', ['1', 'true', 'TRUE'])
    def test_debug_flag_turns_debug_on_outside_production(self, monkeypatch, value):
        """Production forces debug off whatever FLASK_DEBUG says"""
        monkeypatch.setenv('FLASK_DEBUG', value)

        assert DevelopmentConfig().FLASK_DEBUG is True
        monkeypatch.setenv('SECRET_KEY', STRONG_SECRET)
        assert ProductionConfig().FLASK_DEBUG is False

    @pytest.mark.parametrize('value', ['0', 'false', ''])
    def test_debug_flag_off_values(self, monkeypatch, value):
        """A set FLASK_DEBUG=0 is off: run_dev.sh's override relies on it"""
        monkeypatch.setenv('FLASK_DEBUG', value)

        assert DevelopmentConfig().FLASK_DEBUG is False

    def test_unit_test_config_attributes(self):
        """UnitTestConfig should have correct attributes"""
        config = UnitTestConfig()

        assert config.SQLALCHEMY_DATABASE_URI == 'sqlite:///:memory:'
        assert config.USES_SERVICES is False
        assert config.RATELIMIT_ENABLED is False

    def test_integration_config_attributes(self):
        """IntegrationConfig should disable rate limiting"""
        config = IntegrationConfig()

        assert config.USES_SERVICES is True
        assert config.RATELIMIT_ENABLED is False

    def test_integration_config_without_e2e_mode(self):
        """Without E2E_MODE, CSRF is off for API tests"""
        config = IntegrationConfig()

        assert config.JWT_COOKIE_CSRF_PROTECT is False

    def test_integration_config_with_e2e_mode(self, monkeypatch):
        """With E2E_MODE, the browser-facing CSRF check comes back on"""
        monkeypatch.setenv('E2E_MODE', 'true')
        config = IntegrationConfig()

        assert config.JWT_COOKIE_CSRF_PROTECT is True

    @pytest.mark.parametrize('config_class', [
        DevelopmentConfig, UnitTestConfig, IntegrationConfig, ProductionConfig])
    def test_refresh_cookie_is_secure_prefixed_everywhere(self, monkeypatch, config_class):
        """Browsers drop a __Secure- cookie that lacks Secure, so both go together"""
        monkeypatch.setenv('SECRET_KEY', STRONG_SECRET)
        config = config_class()

        assert config.JWT_REFRESH_COOKIE_NAME == '__Secure-refresh_token'
        assert config.JWT_COOKIE_SECURE is True

    def test_production_config_attributes(self, monkeypatch):
        """ProductionConfig should have correct attributes"""
        monkeypatch.setenv('SECRET_KEY', STRONG_SECRET)
        config = ProductionConfig()

        assert config.FLASK_DEBUG is False
        assert config.JWT_COOKIE_SECURE is True
        assert config.USES_SERVICES is True
        assert config.RATELIMIT_ENABLED is True


class TestGetConfigFactory:
    """Test get_config() factory function"""

    def test_get_config_development(self, monkeypatch):
        """get_config should return DevelopmentConfig for dev env"""
        monkeypatch.setenv('APP_ENV', 'development')

        config = get_config()

        assert type(config) is DevelopmentConfig
        assert config.SQLALCHEMY_DATABASE_URI.render_as_string(hide_password=False) == SERVICE_ENV['DATABASE_URL']
        assert config.REDIS_URL == SERVICE_ENV['REDIS_URL']

    def test_get_config_unit(self, monkeypatch):
        """get_config should return UnitTestConfig for unit tests"""
        monkeypatch.setenv('APP_ENV', 'unit')

        config = get_config()

        assert type(config) is UnitTestConfig
        assert config.SQLALCHEMY_DATABASE_URI == 'sqlite:///:memory:'
        assert config.USES_SERVICES is False
        assert config.RATELIMIT_ENABLED is False

    def test_e2e_mode_cannot_downgrade_production(self, monkeypatch):
        """E2E_MODE must not swap ProductionConfig for a weaker config"""
        monkeypatch.setenv('APP_ENV', 'production')
        monkeypatch.setenv('E2E_MODE', 'true')
        monkeypatch.setenv('SECRET_KEY', STRONG_SECRET)

        config = get_config()

        assert type(config) is ProductionConfig
        assert config.RATELIMIT_ENABLED is True
        assert config.USES_SERVICES is True
        assert config.JWT_COOKIE_SECURE is True

    def test_get_config_production(self, monkeypatch):
        """get_config should return ProductionConfig for prod env"""
        monkeypatch.setenv('APP_ENV', 'production')
        monkeypatch.setenv('SECRET_KEY', STRONG_SECRET)

        config = get_config()

        assert type(config) is ProductionConfig
        assert config.SQLALCHEMY_DATABASE_URI.render_as_string(hide_password=False) == SERVICE_ENV['DATABASE_URL']
        assert config.REDIS_URL == SERVICE_ENV['REDIS_URL']

    def test_get_config_invalid_env(self, monkeypatch):
        """get_config should raise error for invalid APP_ENV"""
        monkeypatch.setenv('APP_ENV', 'invalid')

        with pytest.raises(ValueError) as exc_info:
            get_config()

        assert 'APP_ENV' in str(exc_info.value)
        assert 'invalid' in str(exc_info.value)

    def test_get_config_defaults_to_production(self, monkeypatch):
        """get_config should default to production if APP_ENV not set"""
        monkeypatch.delenv('APP_ENV', raising=False)
        monkeypatch.setenv('SECRET_KEY', STRONG_SECRET)

        config = get_config()

        assert type(config) is ProductionConfig


class TestGetConfigValidation:
    """Test validation in get_config()"""

    @pytest.mark.parametrize('var', ['DATABASE_URL', 'REDIS_URL'])
    def test_get_config_requires_service_urls_in_dev(self, monkeypatch, var):
        monkeypatch.setenv('APP_ENV', 'development')
        monkeypatch.delenv(var)

        with pytest.raises(ValueError) as exc_info:
            get_config()

        assert str(exc_info.value) == f'Missing required environment variable: {var}'

    def test_unit_test_config_needs_no_service_vars(self, monkeypatch):
        """Unit tests use SQLite with Redis off, so need no database/Redis settings"""
        monkeypatch.setenv('APP_ENV', 'unit')
        for var in SERVICE_ENV:
            monkeypatch.delenv(var)

        config = get_config()

        assert config.SQLALCHEMY_DATABASE_URI == 'sqlite:///:memory:'
        assert config.REDIS_URL is None

    @pytest.mark.parametrize('config_class', [IntegrationConfig, ProductionConfig])
    def test_service_configs_still_require_vars(self, monkeypatch, config_class):
        monkeypatch.setenv('SECRET_KEY', STRONG_SECRET)
        monkeypatch.delenv('DATABASE_URL')

        with pytest.raises(ValueError, match='DATABASE_URL'):
            config_class()

    def test_get_config_requires_secret_key(self, monkeypatch):
        """get_config should raise error if SECRET_KEY missing"""
        monkeypatch.setenv('APP_ENV', 'development')
        monkeypatch.delenv('SECRET_KEY', raising=False)

        with pytest.raises(ValueError) as exc_info:
            get_config()

        assert 'SECRET_KEY' in str(exc_info.value)


class TestDatabaseUrl:
    """Which URL the app connects with, and what it accepts"""

    MIGRATION_URL = 'mysql+pymysql://owner:ownerpass@dbhost:3306/db'

    def test_migration_url_wins_when_set(self, monkeypatch):
        """Only the migrate job (and the integration suite) gets it"""
        monkeypatch.setenv('MIGRATION_DATABASE_URL', self.MIGRATION_URL)

        url = DevelopmentConfig().SQLALCHEMY_DATABASE_URI

        assert (url.username, url.password) == ('owner', 'ownerpass')

    def test_the_apps_own_url_on_request(self, monkeypatch):
        """What the production grant check reads, beside a migration URL"""
        monkeypatch.setenv('MIGRATION_DATABASE_URL', self.MIGRATION_URL)
        monkeypatch.setenv('DATABASE_PASSWORD', 'the-apps')

        url = database_url(migration=False)

        assert (url.username, url.password) == ('user', 'the-apps')

    @pytest.mark.parametrize('url_var, password_var, user', [
        ('DATABASE_URL', 'DATABASE_PASSWORD', 'user'),
        ('MIGRATION_DATABASE_URL', 'MIGRATION_DATABASE_PASSWORD', 'owner'),
    ])
    def test_a_password_variable_replaces_the_urls(self, monkeypatch, url_var, password_var, user):
        """A secrets store can supply the password alone, beside a URL without one"""
        monkeypatch.setenv(url_var, f'mysql+pymysql://{user}@dbhost/db')
        monkeypatch.setenv(password_var, 'from-the-store')

        url = DevelopmentConfig().SQLALCHEMY_DATABASE_URI

        assert (url.username, url.password) == (user, 'from-the-store')

    def test_the_app_password_never_reaches_the_migration_url(self, monkeypatch):
        monkeypatch.setenv('MIGRATION_DATABASE_URL', self.MIGRATION_URL)
        monkeypatch.setenv('DATABASE_PASSWORD', 'the-apps')

        assert DevelopmentConfig().SQLALCHEMY_DATABASE_URI.password == 'ownerpass'

    @pytest.mark.parametrize('password', ['p@ss/w:rd#1', "it's%40\\"])
    def test_any_password_survives_the_url(self, monkeypatch, password):
        monkeypatch.setenv('DATABASE_PASSWORD', password)

        url = DevelopmentConfig().SQLALCHEMY_DATABASE_URI

        assert make_url(url.render_as_string(hide_password=False)).password == password

    def test_a_percent_encoded_password_is_decoded(self, monkeypatch):
        monkeypatch.setenv('DATABASE_URL', 'mysql+pymysql://user:p%40ss%2Fw@dbhost/db')

        assert DevelopmentConfig().SQLALCHEMY_DATABASE_URI.password == 'p@ss/w'

    def test_password_is_hidden_when_printed(self):
        assert str(DevelopmentConfig().SQLALCHEMY_DATABASE_URI) == (
            'mysql+pymysql://user:***@db:3306/db')

    @pytest.mark.parametrize('value', [
        'postgresql://user:pass@dbhost/db', 'mysql://user:pass@dbhost/db'])
    def test_refuses_another_driver(self, monkeypatch, value):
        """The connect args are PyMySQL's"""
        monkeypatch.setenv('DATABASE_URL', value)

        with pytest.raises(ValueError) as exc_info:
            DevelopmentConfig()

        assert str(exc_info.value) == 'DATABASE_URL must start with mysql+pymysql://'

    @pytest.mark.parametrize('value', [
        'mysql+pymysql://dbhost/db',
        'mysql+pymysql://user@dbhost/db',
        'mysql+pymysql://user:pass@/db',
        'mysql+pymysql://user:pass@dbhost',
    ])
    def test_refuses_an_incomplete_url(self, monkeypatch, value):
        monkeypatch.setenv('DATABASE_URL', value)

        with pytest.raises(ValueError) as exc_info:
            DevelopmentConfig()

        assert str(exc_info.value) == (
            'DATABASE_URL must name a user, password, host and database '
            '(the password may be in DATABASE_PASSWORD)')

    def test_refuses_a_malformed_url_without_echoing_it(self, monkeypatch):
        """The value holds a password, and the message reaches the logs"""
        monkeypatch.setenv('MIGRATION_DATABASE_URL', 'secret-pw no scheme')

        with pytest.raises(ValueError) as exc_info:
            DevelopmentConfig()

        assert str(exc_info.value) == 'MIGRATION_DATABASE_URL is not a valid URL'

    @pytest.mark.parametrize('name', ['app_db', 'AppDB2', '_'])
    def test_accepts_a_database_of_letters_digits_and_underscores(self, monkeypatch, name):
        monkeypatch.setenv('DATABASE_URL', f'mysql+pymysql://user:pass@dbhost/{name}')

        assert DevelopmentConfig().SQLALCHEMY_DATABASE_URI.database == name

    @pytest.mark.parametrize('name', ['app-db', 'app%25db', 'app%60db', 'app.db', 'bücher'])
    def test_refuses_any_other_database_name(self, monkeypatch, name):
        """Only such a name is safe between backticks, with `_` its one GRANT
        wildcard, which the production grant check escapes"""
        monkeypatch.setenv('MIGRATION_DATABASE_URL', f'mysql+pymysql://user:pass@dbhost/{name}')

        with pytest.raises(ValueError) as exc_info:
            DevelopmentConfig()

        assert str(exc_info.value) == (
            'MIGRATION_DATABASE_URL must name a database of letters, digits and _ alone')


class TestRedisUrl:
    """What REDIS_URL accepts, and how REDIS_PASSWORD joins it"""

    def test_redis_password_replaces_the_urls(self, monkeypatch):
        monkeypatch.setenv('REDIS_URL', 'redis://app@redishost:6379/0')
        monkeypatch.setenv('REDIS_PASSWORD', 'r@dis/pw')

        url = DevelopmentConfig().REDIS_URL

        assert url == 'redis://app:r%40dis%2Fpw@redishost:6379/0'
        assert parse_url(url)['password'] == 'r@dis/pw'

    def test_a_percent_encoded_password_is_kept(self, monkeypatch):
        monkeypatch.setenv('REDIS_URL', 'redis://app:r%40dis@redishost:6379/0')

        assert parse_url(DevelopmentConfig().REDIS_URL)['password'] == 'r@dis'

    def test_tls_and_options_are_kept(self, monkeypatch):
        value = 'rediss://app:pw@cache.example.com:6380/2?ssl_cert_reqs=required'
        monkeypatch.setenv('REDIS_URL', value)

        assert DevelopmentConfig().REDIS_URL == value

    def test_a_ca_bundle_path_reaches_redis_intact(self, monkeypatch):
        """The URL is rebuilt, which percent-encodes the path's slashes"""
        monkeypatch.setenv(
            'REDIS_URL', 'rediss://app:pw@cache.example.com:6380/2?ssl_ca_certs=/etc/ssl/ca.pem')

        assert parse_url(DevelopmentConfig().REDIS_URL)['ssl_ca_certs'] == '/etc/ssl/ca.pem'

    @pytest.mark.parametrize('value', ['http://app:pw@redishost/0', 'unix:///tmp/redis.sock'])
    def test_refuses_another_scheme(self, monkeypatch, value):
        monkeypatch.setenv('REDIS_URL', value)

        with pytest.raises(ValueError) as exc_info:
            DevelopmentConfig()

        assert str(exc_info.value) == 'REDIS_URL must start with redis:// or rediss:// (TLS)'

    @pytest.mark.parametrize('value', [
        # No user: the compose files disable Redis's "default" user
        'redis://:pw@redishost:6379/0',
        'redis://redishost:6379/0',
        'redis://app@redishost:6379/0',
        'redis://app:pw@:6379/0',
    ])
    def test_refuses_an_incomplete_url(self, monkeypatch, value):
        monkeypatch.setenv('REDIS_URL', value)

        with pytest.raises(ValueError) as exc_info:
            DevelopmentConfig()

        assert str(exc_info.value) == (
            'REDIS_URL must name a user, password and host '
            '(the password may be in REDIS_PASSWORD)')

    def test_refuses_a_malformed_url_without_echoing_it(self, monkeypatch):
        monkeypatch.setenv('REDIS_URL', 'redis://app:secret-pw@redishost:port/0')

        with pytest.raises(ValueError) as exc_info:
            DevelopmentConfig()

        assert str(exc_info.value) == 'REDIS_URL is not a valid URL'


class TestConfigValues:
    """Test specific configuration values"""

    def test_jwt_token_expiration_configured(self, monkeypatch):
        """JWT token expiration should be set"""
        monkeypatch.setenv('APP_ENV', 'development')

        config = get_config()

        assert config.JWT_ACCESS_TOKEN_EXPIRES == timedelta(minutes=15)
        assert config.JWT_REFRESH_TOKEN_EXPIRES == timedelta(days=30)
        assert config.SESSION_IDLE_TIMEOUT == timedelta(days=7)

    def test_jwt_cookie_settings(self, monkeypatch):
        """JWT cookie settings should be configured for security"""
        monkeypatch.setenv('APP_ENV', 'development')

        config = get_config()

        assert config.JWT_COOKIE_SAMESITE == 'Lax'
        assert config.JWT_COOKIE_CSRF_PROTECT is True

    def test_redis_pool_size(self):
        assert DevelopmentConfig().REDIS_MAX_CONNECTIONS == 50

    @pytest.mark.parametrize('config_class', [DevelopmentConfig, IntegrationConfig])
    def test_pool_checks_connections_before_use(self, config_class):
        """Every MySQL config: a connection MySQL dropped must not reach a
        request. tests/integration/test_mysql_pool.py shows it working."""
        options = config_class().SQLALCHEMY_ENGINE_OPTIONS
        assert options['pool_pre_ping'] is True
        assert options['pool_recycle'] < 8 * 3600

    @pytest.mark.parametrize('config_class', [DevelopmentConfig, IntegrationConfig])
    def test_connections_use_utc(self, config_class):
        """NOW() defaults must be UTC whatever the server's own time zone.
        tests/integration/test_mysql_time_zone.py shows it working."""
        options = config_class().SQLALCHEMY_ENGINE_OPTIONS
        assert options['connect_args']['init_command'] == "SET time_zone = '+00:00'"

    @pytest.mark.parametrize('config_class', [
        DevelopmentConfig, UnitTestConfig, IntegrationConfig, ProductionConfig])
    def test_sql_parameters_stay_out_of_the_logs(self, config_class, monkeypatch):
        """A failed statement's values (password hashes, emails, note text)
        must not reach the log. test_app_factory.py shows it working."""
        monkeypatch.setenv('SECRET_KEY', STRONG_SECRET)

        options = config_class().SQLALCHEMY_ENGINE_OPTIONS

        assert options['hide_parameters'] is True

    @pytest.mark.parametrize('config_class', [DevelopmentConfig, IntegrationConfig])
    def test_database_calls_time_out(self, config_class, monkeypatch):
        """A hung database must not hold request threads forever.
        tests/integration/test_mysql_timeouts.py shows it working."""
        monkeypatch.delenv('DB_QUERY_TIMEOUT', raising=False)

        args = config_class().SQLALCHEMY_ENGINE_OPTIONS['connect_args']

        assert (args['connect_timeout'], args['read_timeout'], args['write_timeout']) == (5, 15, 15)

    def test_query_timeout_can_be_lifted_for_migrations(self, monkeypatch):
        """The migrate service sets 0: a migration may run longer than a request"""
        monkeypatch.setenv('DB_QUERY_TIMEOUT', '0')

        args = DevelopmentConfig().SQLALCHEMY_ENGINE_OPTIONS['connect_args']

        assert 'read_timeout' not in args and 'write_timeout' not in args
        assert args['connect_timeout'] == 5


class TestConfigInheritance:
    """Test that child configs inherit from base Config"""

    def test_development_inherits_jwt_settings(self):
        """DevelopmentConfig should inherit JWT settings from Config"""
        config = DevelopmentConfig()

        assert hasattr(config, 'JWT_ACCESS_TOKEN_EXPIRES')
        assert hasattr(config, 'JWT_REFRESH_TOKEN_EXPIRES')
        assert hasattr(config, 'JWT_SECRET_KEY')

    def test_development_inherits_redis_settings(self):
        """DevelopmentConfig should inherit Redis settings from Config"""
        config = DevelopmentConfig()

        assert hasattr(config, 'REDIS_URL')
        assert hasattr(config, 'REDIS_MAX_CONNECTIONS')

    def test_integration_inherits_from_config(self):
        """IntegrationConfig should inherit all base settings"""
        config = IntegrationConfig()

        assert hasattr(config, 'JWT_ACCESS_TOKEN_EXPIRES')
        assert hasattr(config, 'REDIS_URL')
        assert hasattr(config, 'SQLALCHEMY_DATABASE_URI')


class TestRateLimitBehavior:
    """Test rate limiting configuration across environments"""

    def test_rate_limiting_enabled_in_development(self):
        """Rate limiting should be enabled in development"""
        config = DevelopmentConfig()
        assert config.RATELIMIT_ENABLED is True

    def test_rate_limiting_disabled_in_unit_tests(self):
        """Rate limiting should be disabled in unit tests"""
        config = UnitTestConfig()
        assert config.RATELIMIT_ENABLED is False

    def test_rate_limiting_disabled_in_integration(self):
        """Rate limiting is off in integration to allow unlimited test traffic"""
        config = IntegrationConfig()
        assert config.RATELIMIT_ENABLED is False

    def test_rate_limiting_enabled_in_production(self, monkeypatch):
        """Rate limiting should be enabled in production"""
        monkeypatch.setenv('SECRET_KEY', STRONG_SECRET)
        config = ProductionConfig()
        assert config.RATELIMIT_ENABLED is True


class TestProductionSecretKey:
    """ProductionConfig refuses secrets that would let anyone forge JWTs"""

    def test_rejects_short_secret(self, monkeypatch):
        monkeypatch.setenv('SECRET_KEY', 'x' * 31)

        with pytest.raises(ValueError, match='SECRET_KEY'):
            ProductionConfig()

    def test_rejects_template_placeholder(self, monkeypatch):
        monkeypatch.setenv('SECRET_KEY', 'your_secret_key_here')

        with pytest.raises(ValueError, match='SECRET_KEY'):
            ProductionConfig()

    def test_accepts_long_secret(self, monkeypatch):
        monkeypatch.setenv('SECRET_KEY', STRONG_SECRET)

        assert ProductionConfig().JWT_SECRET_KEY == STRONG_SECRET

    @pytest.mark.parametrize('var, value, service', [
        ('DATABASE_URL', 'mysql+pymysql://u:your_db_password_here@db/d', 'database'),
        ('DATABASE_PASSWORD', 'your_db_password_here', 'database'),
        ('MIGRATION_DATABASE_URL',
         'mysql+pymysql://u:your_migration_password_here@db/d', 'database'),
        ('REDIS_URL', 'redis://app:your_redis_password_here@redis:6379/0', 'Redis'),
        ('REDIS_PASSWORD', 'your_redis_password_here', 'Redis'),
    ])
    def test_rejects_placeholder_passwords(self, monkeypatch, var, value, service):
        monkeypatch.setenv('SECRET_KEY', STRONG_SECRET)
        monkeypatch.setenv(var, value)

        with pytest.raises(ValueError) as exc_info:
            ProductionConfig()

        assert str(exc_info.value) == (
            f'The {service} password is still the .env.prod.example placeholder')

    def test_rejects_the_app_users_placeholder_beside_a_migration_url(self, monkeypatch):
        """The migrate job logs in as DATABASE_URL's user too"""
        monkeypatch.setenv('SECRET_KEY', STRONG_SECRET)
        monkeypatch.setenv('MIGRATION_DATABASE_URL', 'mysql+pymysql://owner:ownerpass@db/d')
        monkeypatch.setenv('DATABASE_PASSWORD', 'your_db_password_here')

        with pytest.raises(ValueError) as exc_info:
            ProductionConfig()

        assert str(exc_info.value) == (
            'The database password is still the .env.prod.example placeholder')

    def test_short_secret_allowed_outside_production(self, monkeypatch):
        monkeypatch.setenv('SECRET_KEY', 'short')

        assert DevelopmentConfig().JWT_SECRET_KEY == 'short'


class TestTrustedProxyCount:
    """Rate limits key on the address the trusted proxies report"""

    @pytest.fixture(autouse=True)
    def strong_secret(self, monkeypatch):
        monkeypatch.setenv('SECRET_KEY', STRONG_SECRET)

    def test_production_trusts_nginx_by_default(self):
        assert ProductionConfig().TRUSTED_PROXY_COUNT == 1

    @pytest.mark.parametrize('value, count', [('0', 0), ('2', 2)])
    def test_a_deployment_sets_its_own_count(self, monkeypatch, value, count):
        monkeypatch.setenv('TRUSTED_PROXY_COUNT', value)

        assert ProductionConfig().TRUSTED_PROXY_COUNT == count

    @pytest.mark.parametrize('value', ['-1', 'abc', '', '1.5', '٢'])
    def test_refuses_anything_but_a_whole_number(self, monkeypatch, value):
        monkeypatch.setenv('TRUSTED_PROXY_COUNT', value)

        with pytest.raises(ValueError, match='TRUSTED_PROXY_COUNT must be a whole number'):
            ProductionConfig()

    def test_only_production_reads_it(self, monkeypatch):
        monkeypatch.setenv('TRUSTED_PROXY_COUNT', '2')

        assert DevelopmentConfig().TRUSTED_PROXY_COUNT == 0


class TestProductionTls:
    """Production reaches a database or Redis outside the bundled services
    only over TLS that checks the server's certificate and name"""

    @pytest.fixture(autouse=True)
    def strong_secret(self, monkeypatch):
        monkeypatch.setenv('SECRET_KEY', STRONG_SECRET)

    EXTERNAL_DATABASE = 'mysql+pymysql://user:dbpass@mydb.example.com:3306/db'
    EXTERNAL_REDIS = 'redis://app:redispass@cache.example.com:6379/0'

    @pytest.mark.parametrize('var, value', [
        ('DATABASE_URL', f'{EXTERNAL_DATABASE}?ssl_ca=/etc/ssl/certs/ca-certificates.crt'),
        ('REDIS_URL', EXTERNAL_REDIS.replace('redis://', 'rediss://')),
        ('REDIS_URL', EXTERNAL_REDIS.replace('redis://', 'rediss://') + '?ssl_ca_certs=/ca.pem'),
    ])
    def test_accepts_an_external_host_over_tls(self, monkeypatch, var, value):
        monkeypatch.setenv(var, value)

        assert ProductionConfig().RATELIMIT_ENABLED is True

    def test_refuses_an_external_database_without_a_ca_bundle(self, monkeypatch):
        monkeypatch.setenv('DATABASE_URL', f'{self.EXTERNAL_DATABASE}?charset=utf8mb4')

        with pytest.raises(ValueError) as exc_info:
            ProductionConfig()

        assert str(exc_info.value) == (
            'A database host other than db needs TLS: add ?ssl_ca=<CA bundle path> to DATABASE_URL')

    @pytest.mark.parametrize('with_tls, without_tls', [
        ('MIGRATION_DATABASE_URL', 'DATABASE_URL'),
        ('DATABASE_URL', 'MIGRATION_DATABASE_URL'),
    ])
    def test_every_database_url_needs_tls_not_only_the_one_in_use(
            self, monkeypatch, with_tls, without_tls):
        """The migrate job logs in as DATABASE_URL's user too, to read its grants"""
        monkeypatch.setenv(with_tls, f'{self.EXTERNAL_DATABASE}?ssl_ca=/ca.pem')
        monkeypatch.setenv(without_tls, self.EXTERNAL_DATABASE)

        with pytest.raises(ValueError) as exc_info:
            ProductionConfig()

        assert str(exc_info.value) == (
            f'A database host other than db needs TLS: add ?ssl_ca=<CA bundle path> '
            f'to {without_tls}')

    def test_accepts_both_database_urls_over_tls(self, monkeypatch):
        for var in ('MIGRATION_DATABASE_URL', 'DATABASE_URL'):
            monkeypatch.setenv(var, f'{self.EXTERNAL_DATABASE}?ssl_ca=/ca.pem')

        assert ProductionConfig().SQLALCHEMY_DATABASE_URI.query == {'ssl_ca': '/ca.pem'}

    @pytest.mark.parametrize('option', [
        'ssl_check_hostname=false', 'ssl_verify_cert=false',
        'ssl_verify_identity=false', 'ssl_disabled=true'])
    def test_refuses_a_database_option_that_could_skip_checks(self, monkeypatch, option):
        monkeypatch.setenv('DATABASE_URL', f'{self.EXTERNAL_DATABASE}?ssl_ca=/ca.pem&{option}')

        with pytest.raises(ValueError) as exc_info:
            ProductionConfig()

        assert str(exc_info.value) == (
            f"DATABASE_URL may not set {option.split('=')[0]}: production checks "
            f"the server's certificate and name")

    def test_refuses_an_external_redis_without_tls(self, monkeypatch):
        monkeypatch.setenv('REDIS_URL', self.EXTERNAL_REDIS)

        with pytest.raises(ValueError) as exc_info:
            ProductionConfig()

        assert str(exc_info.value) == (
            'A Redis host other than redis needs TLS: start REDIS_URL with rediss://')

    def test_refuses_redis_options_that_could_skip_checks(self, monkeypatch):
        monkeypatch.setenv('REDIS_URL', self.EXTERNAL_REDIS.replace('redis://', 'rediss://')
                           + '?ssl_cert_reqs=none&ssl_check_hostname=false')

        with pytest.raises(ValueError) as exc_info:
            ProductionConfig()

        assert str(exc_info.value) == (
            "REDIS_URL may not set ssl_cert_reqs, ssl_check_hostname: production "
            "checks the server's certificate and name")

    def test_external_hosts_need_no_tls_outside_production(self, monkeypatch):
        monkeypatch.setenv('DATABASE_URL', self.EXTERNAL_DATABASE)
        monkeypatch.setenv('REDIS_URL', self.EXTERNAL_REDIS)

        assert DevelopmentConfig().SQLALCHEMY_DATABASE_URI.host == 'mydb.example.com'
