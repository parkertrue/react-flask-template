"""wait_for_services.py, which every container runs before its command.

The checks themselves are faked: what matters here is the loop around them,
which must give up on a typo at once and on a dead service after the timeout,
saying why each service is not ready, and never printing a password. In
production it must also refuse an app user that may change the schema.
"""
import json
from unittest.mock import MagicMock

import pymysql
import pytest
import redis
from sqlalchemy import create_engine
from sqlalchemy.exc import OperationalError

import wait_for_services as wait
from app.config import database_url, redis_url

ENV = {
    'DATABASE_URL': 'mysql+pymysql://app:db-secret@db:3306/app',
    'REDIS_URL': 'redis://app:redis-secret@redis:6379/0',
}


@pytest.fixture
def env(monkeypatch):
    """Development's settings: the tests of production set APP_ENV themselves"""
    monkeypatch.setenv('APP_ENV', 'development')
    for name in ('MIGRATION_DATABASE_URL', 'DATABASE_PASSWORD',
                 'MIGRATION_DATABASE_PASSWORD', 'REDIS_PASSWORD'):
        monkeypatch.delenv(name, raising=False)
    for name, value in ENV.items():
        monkeypatch.setenv(name, value)


@pytest.fixture
def clock(monkeypatch):
    """A fake clock that sleeping advances, so waiting takes no real time"""
    now = [0.0]
    monkeypatch.setattr(wait.time, 'monotonic', lambda: now[0])
    monkeypatch.setattr(wait.time, 'sleep', lambda s: now.__setitem__(0, now[0] + s))
    return now


def logged(capsys):
    """What the script wrote, as (level, message) pairs: every line is JSON"""
    return [(line['level'], line['message']) for line in
            map(json.loads, capsys.readouterr().out.splitlines())]


def services(monkeypatch, mysql, redis_):
    """Fake the two checks: each answers from its list, repeating the last.
    None means ready; anything else is the error."""
    def check(answers):
        return lambda url, secrets: answers.pop(0) if len(answers) > 1 else answers[0]
    monkeypatch.setattr(wait, 'mysql_error', check(mysql))
    monkeypatch.setattr(wait, 'redis_error', check(redis_))


def test_missing_settings_fail_at_once_naming_them(env, monkeypatch, capsys):
    for name in ENV:
        monkeypatch.delenv(name)
    monkeypatch.setattr(wait, 'mysql_error', lambda *args: pytest.fail('should not connect'))

    with pytest.raises(SystemExit) as exit_info:
        wait.main()

    assert exit_info.value.code == 1
    assert logged(capsys) == [
        ('ERROR', 'Missing required environment variables: DATABASE_URL, REDIS_URL')]


def test_a_malformed_url_fails_at_once_saying_so(env, monkeypatch, capsys):
    monkeypatch.setenv('REDIS_URL', 'http://app:redis-secret@redis/0')
    monkeypatch.setattr(wait, 'mysql_error', lambda *args: pytest.fail('should not connect'))

    with pytest.raises(SystemExit) as exit_info:
        wait.main()

    assert exit_info.value.code == 1
    assert logged(capsys) == [
        ('ERROR', 'REDIS_URL must start with redis:// or rediss:// (TLS)')]


def test_a_url_production_refuses_fails_at_once(env, monkeypatch, capsys):
    """Before any wait: a server that requires TLS would refuse every try"""
    monkeypatch.setenv('APP_ENV', 'production')
    monkeypatch.setenv('SECRET_KEY', 'x' * 32)
    monkeypatch.setenv('DATABASE_URL', 'mysql+pymysql://app:db-secret@mydb.example.com/app')
    monkeypatch.setattr(wait, 'mysql_error', lambda *args: pytest.fail('should not connect'))

    with pytest.raises(SystemExit) as exit_info:
        wait.main()

    assert exit_info.value.code == 1
    assert logged(capsys) == [('ERROR', (
        'A database host other than db needs TLS: add ?ssl_ca=<CA bundle path> to DATABASE_URL'))]


def test_the_migrate_job_checks_the_app_users_url_before_logging_in(env, monkeypatch, capsys):
    """migrate logs in as DATABASE_URL's user too, to read its grants: TLS on
    the migration URL alone would send that password in the clear"""
    monkeypatch.setenv('APP_ENV', 'production')
    monkeypatch.setenv('SECRET_KEY', 'x' * 32)
    monkeypatch.setenv('MIGRATION_DATABASE_URL',
                       'mysql+pymysql://owner:owner-secret@mydb.example.com/app?ssl_ca=/ca.pem')
    monkeypatch.setenv('DATABASE_URL', 'mysql+pymysql://app:db-secret@mydb.example.com/app')
    monkeypatch.setattr(wait, 'mysql_error', lambda *args: pytest.fail('should not connect'))
    monkeypatch.setattr(wait, 'schema_rights', lambda url: pytest.fail('should not connect'))

    with pytest.raises(SystemExit) as exit_info:
        wait.main()

    assert exit_info.value.code == 1
    assert logged(capsys) == [('ERROR', (
        'A database host other than db needs TLS: add ?ssl_ca=<CA bundle path> to DATABASE_URL'))]


def test_checks_the_urls_the_app_will_use(env, clock, monkeypatch):
    """The migration user's when it is set, and each password variable"""
    monkeypatch.setenv('MIGRATION_DATABASE_URL', 'mysql+pymysql://owner@db/app')
    monkeypatch.setenv('MIGRATION_DATABASE_PASSWORD', 'owner-secret')
    monkeypatch.setenv('REDIS_PASSWORD', 'other-secret')
    checked = []
    monkeypatch.setattr(wait, 'mysql_error', lambda url, secrets: checked.append(url))
    monkeypatch.setattr(wait, 'redis_error', lambda url, secrets: checked.append(url))

    wait.main()

    assert [str(url) for url in checked] == [
        'mysql+pymysql://owner:***@db/app', 'redis://app:other-secret@redis:6379/0']
    assert checked[0].password == 'owner-secret'


def test_returns_once_both_services_answer(env, clock, monkeypatch, capsys):
    services(monkeypatch, mysql=['refused', None], redis_=['refused', 'refused', None])

    wait.main()

    assert logged(capsys) == [
        ('INFO', 'Waiting for: MySQL (refused), Redis (refused)'),
        ('INFO', 'Waiting for: Redis (refused)'),
        ('INFO', 'Database and Redis are up'),
    ]
    assert clock[0] == 2


def test_an_unchanged_wait_is_printed_once(env, clock, monkeypatch, capsys):
    services(monkeypatch, mysql=['booting', 'booting', 'booting', None], redis_=[None])

    wait.main()

    assert logged(capsys) == [
        ('INFO', 'Waiting for: MySQL (booting)'),
        ('INFO', 'Database and Redis are up'),
    ]


def test_gives_up_after_the_timeout_naming_what_is_down(env, clock, monkeypatch, capsys):
    services(monkeypatch, mysql=[None], redis_=['refused'])

    with pytest.raises(SystemExit) as exit_info:
        wait.main()

    assert exit_info.value.code == 1
    assert clock[0] > wait.TIMEOUT_SECONDS
    assert logged(capsys) == [
        ('INFO', 'Waiting for: Redis (refused)'),
        ('ERROR', f'Gave up after {wait.TIMEOUT_SECONDS}s waiting for: Redis (refused)'),
    ]


def test_every_password_is_masked_in_what_is_logged(env, clock, monkeypatch, capsys):
    """A driver may echo back what it was given; the log must not"""
    def refuse_mysql(url, **kwargs):
        raise OperationalError('connect', {}, Exception('bad login db-secret'))

    def refuse_redis(self):
        raise redis.AuthenticationError('bad login redis-secret')

    monkeypatch.setattr(wait, 'create_engine', refuse_mysql)
    monkeypatch.setattr(redis.Redis, 'ping', refuse_redis)

    with pytest.raises(SystemExit):
        wait.main()

    messages = [message for _, message in logged(capsys)]
    # Waiting, then giving up: each names MySQL's error and Redis's
    assert [message.count('bad login ***') for message in messages] == [2, 2]
    assert ['secret' in message for message in messages] == [False, False]


def test_a_check_that_raises_reports_why(env, monkeypatch):
    """A wrong password looks like a slow start unless the log says which it is"""
    def refuse_mysql(**kwargs):
        raise pymysql.err.OperationalError(1045, "Access denied for user 'app'")

    def refuse_redis(self):
        raise redis.AuthenticationError('invalid username-password pair')

    monkeypatch.setattr(pymysql, 'connect', refuse_mysql)
    monkeypatch.setattr(redis.Redis, 'ping', refuse_redis)

    mysql = wait.mysql_error(database_url(), [])
    assert mysql.startswith("(pymysql.err.OperationalError) (1045, \"Access denied for user 'app'\")")
    assert wait.redis_error(redis_url(), []) == 'invalid username-password pair'


def test_an_error_without_a_message_is_named_by_its_type(env, monkeypatch):
    def time_out(self):
        raise redis.TimeoutError()
    monkeypatch.setattr(redis.Redis, 'ping', time_out)

    assert wait.redis_error(redis_url(), []) == 'TimeoutError'


def test_a_check_that_connects_reports_no_error(env, monkeypatch):
    """The MySQL check goes through SQLAlchemy, which any database URL works with"""
    sqlite = create_engine('sqlite://')
    monkeypatch.setattr(wait, 'create_engine', lambda url, **kwargs: sqlite)
    monkeypatch.setattr(redis.Redis, 'ping', lambda self: True)

    assert wait.mysql_error(database_url(), []) is None
    assert wait.redis_error(redis_url(), []) is None


def test_the_mysql_check_gives_up_on_a_connection_quickly(env, monkeypatch):
    made = []

    def engine(url, **kwargs):
        made.append(kwargs['connect_args'])
        raise OperationalError('connect', {}, Exception('refused'))
    monkeypatch.setattr(wait, 'create_engine', engine)

    wait.mysql_error(database_url(), [])

    assert made == [{'connect_timeout': 2}]


# What db/init/01-app-user.sh grants the app's user, in ENV's database
APP_USER_GRANTS = [
    'GRANT USAGE ON *.* TO `app`@`%`',
    'GRANT SELECT, INSERT, UPDATE, DELETE ON `app`.* TO `app`@`%`',
]


@pytest.mark.parametrize('grant, allowed', [
    *[(grant, True) for grant in APP_USER_GRANTS],
    ('GRANT SELECT ON `app`.* TO `app`@`%`', True),
    ('GRANT SELECT, INSERT ON `app`.`notes` TO `app`@`%`', True),
    ('GRANT SELECT ON *.* TO `app`@`%`', False),
    ('GRANT INSERT, UPDATE ON *.* TO `app`@`%`', False),
    ('GRANT ALL PRIVILEGES ON `app`.* TO `app`@`%`', False),
    ('GRANT SELECT, INSERT, UPDATE, DELETE, CREATE ON `app`.* TO `app`@`%`', False),
    ('GRANT ALTER ON `app`.`users` TO `app`@`%`', False),
    ('GRANT SELECT ON `app`.* TO `app`@`%` WITH GRANT OPTION', False),
    ('GRANT SELECT (`email`) ON `app`.`users` TO `app`@`%`', False),
    ('GRANT `rds_superuser_role`@`%` TO `admin`@`%`', False),
    # Rows in any other database: MySQL's own grant tables, another app's
    ('GRANT SELECT, INSERT, UPDATE, DELETE ON `mysql`.* TO `app`@`%`', False),
    ('GRANT INSERT, UPDATE ON `mysql`.`user` TO `app`@`%`', False),
    ('GRANT SELECT ON `otherapp`.* TO `app`@`%`', False),
    ('GRANT SELECT ON `appx`.* TO `app`@`%`', False),
    # Not a target SHOW GRANTS prints
    ('GRANT SELECT ON `app`.notes TO `app`@`%`', False),
])
def test_the_app_user_may_hold_data_privileges_alone(grant, allowed):
    assert wait.data_only(grant, 'app') is allowed


@pytest.mark.parametrize('grant, allowed', [
    ('GRANT SELECT, INSERT, UPDATE, DELETE ON `app\\_db`.* TO `app`@`%`', True),
    ('GRANT SELECT, INSERT ON `app\\_db`.`notes` TO `app`@`%`', True),
    # Unescaped, `_` is a wildcard: the grant covers appXdb too
    ('GRANT SELECT, INSERT, UPDATE, DELETE ON `app_db`.* TO `app`@`%`', False),
])
def test_a_grant_names_the_database_as_mysql_escapes_it(grant, allowed):
    assert wait.data_only(grant, 'app_db') is allowed


@pytest.fixture
def production(env, clock, monkeypatch):
    """Production, with both services up: what each grant check read"""
    monkeypatch.setenv('APP_ENV', 'production')
    services(monkeypatch, mysql=[None], redis_=[None])
    checked = []

    def rights(granted):
        def schema_rights(url):
            checked.append(url)
            return granted
        monkeypatch.setattr(wait, 'schema_rights', schema_rights)
    return checked, rights


def test_the_grant_check_runs_in_production_alone(env, clock, monkeypatch, capsys):
    services(monkeypatch, mysql=[None], redis_=[None])
    monkeypatch.setattr(wait, 'schema_rights', lambda url: pytest.fail('not in development'))

    wait.main()

    assert logged(capsys) == [('INFO', 'Database and Redis are up')]


def test_production_starts_when_the_app_user_holds_data_rights_only(production, capsys):
    checked, rights = production
    rights([])

    wait.main()

    assert [str(url) for url in checked] == ['mysql+pymysql://app:***@db:3306/app']
    assert logged(capsys) == [('INFO', 'Database and Redis are up')]


def test_production_refuses_an_app_user_that_may_change_the_schema(production, capsys):
    _, rights = production
    rights(['GRANT ALL PRIVILEGES ON `app`.* TO `app`@`%`'])

    with pytest.raises(SystemExit) as exit_info:
        wait.main()

    assert exit_info.value.code == 1
    assert logged(capsys)[-1] == ('ERROR', (
        "DATABASE_URL's user may do more than read and write rows in its own database: "
        "GRANT ALL PRIVILEGES ON `app`.* TO `app`@`%`. Give the app a user with "
        "SELECT, INSERT, UPDATE and DELETE on its database alone (README, External "
        "Database or Redis)"))


def test_the_migrate_job_checks_the_app_user_not_its_own(production, monkeypatch):
    """The app will connect as DATABASE_URL's user, whatever migrate ran as"""
    checked, rights = production
    rights([])
    monkeypatch.setenv('MIGRATION_DATABASE_URL', 'mysql+pymysql://owner:owner-secret@db/app')

    wait.main()

    assert [url.username for url in checked] == ['app']


def test_production_needs_database_url_beside_a_migration_url(production, monkeypatch, capsys):
    _, rights = production
    rights([])
    monkeypatch.setenv('MIGRATION_DATABASE_URL', 'mysql+pymysql://owner:owner-secret@db/app')
    monkeypatch.delenv('DATABASE_URL')

    with pytest.raises(SystemExit) as exit_info:
        wait.main()

    assert exit_info.value.code == 1
    assert logged(capsys) == [('ERROR', 'Missing required environment variables: DATABASE_URL')]


def test_unreadable_grants_stop_production_with_passwords_masked(production, monkeypatch, capsys):
    monkeypatch.setenv('MIGRATION_DATABASE_URL', 'mysql+pymysql://owner:owner-secret@db/app')

    def refuse(url):
        raise OperationalError('connect', {}, Exception('lost db-secret owner-secret'))
    monkeypatch.setattr(wait, 'schema_rights', refuse)

    with pytest.raises(SystemExit) as exit_info:
        wait.main()

    assert exit_info.value.code == 1
    level, message = logged(capsys)[-1]
    assert (level, message.startswith("Could not read the grants of DATABASE_URL's user: ")) == (
        'ERROR', True)
    assert (message.count('lost *** ***'), 'secret' in message) == (1, False)


def test_schema_rights_reads_the_users_grants(env, monkeypatch):
    """Through SQLAlchemy; tests/integration/test_db_users.py runs it on MySQL"""
    run = []
    rows = [*APP_USER_GRANTS, 'GRANT DROP ON *.* TO `app`@`%`']
    connection = MagicMock()
    connection.__enter__.return_value.execute.side_effect = lambda statement: (
        run.append(str(statement)) or MagicMock(**{'scalars.return_value.all.return_value': rows}))
    engine = MagicMock(**{'connect.return_value': connection})
    engine.dispose.side_effect = lambda: run.append('disposed')
    monkeypatch.setattr(wait, 'create_engine', lambda url, **kwargs: engine)

    assert wait.schema_rights(database_url()) == ['GRANT DROP ON *.* TO `app`@`%`']
    assert run == ['SHOW GRANTS FOR CURRENT_USER()', 'disposed']
