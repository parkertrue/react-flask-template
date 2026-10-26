"""wait_for_services.py, which every container runs before its command.

The checks themselves are faked: what matters here is the loop around them,
which must give up on a typo at once and on a dead service after the timeout,
saying why each service is not ready, and never printing a password.
"""
import json

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
