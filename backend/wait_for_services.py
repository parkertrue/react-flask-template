"""Block until MySQL and Redis accept connections, or exit 1 after a timeout.

Run by entrypoint.sh before the container's command (gunicorn, or the
migrate service's `flask db upgrade`) and by run_dev.sh (local dev). Reads
the URLs as app/config.py does, so it logs in as the app will. Logs as the
app does, one JSON object per line on stdout, so every line the backend
container writes parses alike.

In production it then refuses to start if DATABASE_URL's user may do more
than read and write rows in its own database: only the migration user may
change the schema.
"""
import logging
import os
import re
import sys
import time
from urllib.parse import unquote, urlsplit

import redis
from sqlalchemy import create_engine, text
from sqlalchemy.pool import NullPool

from app.config import database_url, get_config, redis_url
from app.utils.log import JsonFormatter

log = logging.getLogger('wait_for_services')
log.setLevel(logging.INFO)

# Matches the backend healthcheck's start_period (docker-compose.yml and
# docker-compose.test.yml), which covers this wait: change them together.
TIMEOUT_SECONDS = 60

# All the app's own database user may hold: rows in its database, and on
# *.* only USAGE, MySQL's word for no privilege at all. Rows anywhere else
# could be MySQL's own grant tables (mysql.*) or another app's.
DATA_PRIVILEGES = {'SELECT', 'INSERT', 'UPDATE', 'DELETE'}
# One row of SHOW GRANTS: privileges on one object. Anything else (a role, a
# column grant, WITH GRANT OPTION) fails to match, and so is refused.
GRANT_ROW = re.compile(r'GRANT (?P<privileges>[A-Z ,]+) ON (?P<target>\S+) TO \S+')
# What may follow the database in a grant's target: all its tables, or one
TABLES = re.compile(r'\*|`[^`]+`')


def describe(error, secrets):
    """The error's text, with every password in it masked: a driver may
    echo back what it was given"""
    text = str(error) or type(error).__name__
    for secret in secrets:
        text = text.replace(secret, '***')
    return text


def mysql_error(url, secrets):
    """None once MySQL accepts this login, else why it does not"""
    try:
        engine = create_engine(url, poolclass=NullPool, connect_args={'connect_timeout': 2})
        engine.connect().close()
        engine.dispose()
        return None
    except Exception as error:
        return describe(error, secrets)


def redis_error(url, secrets):
    """None once Redis accepts this login, else why it does not"""
    try:
        client = redis.Redis.from_url(url, socket_connect_timeout=2)
        client.ping()
        client.close()
        return None
    except Exception as error:
        return describe(error, secrets)


def data_only(grant, database):
    """Whether one row of SHOW GRANTS gives no more than DATA_PRIVILEGES,
    and those in `database` alone"""
    match = GRANT_ROW.fullmatch(grant)
    if not match:
        return False
    privileges = set(match['privileges'].split(', '))
    if match['target'] == '*.*':
        return privileges == {'USAGE'}
    # SHOW GRANTS prints the name as it was granted, and `_` is a GRANT
    # wildcard: unescaped, `app_db` covers appXdb too. The name holds nothing
    # else that needs escaping (DATABASE_NAME in app/config.py).
    target, _, tables = match['target'].partition('.')
    return (target == f"`{database.replace('_', r'\_')}`"
            and TABLES.fullmatch(tables) is not None
            and privileges <= DATA_PRIVILEGES)


def schema_rights(url):
    """The grants that let this login do more than read and write rows in
    its own database, from MySQL's own list: none for the app's user"""
    engine = create_engine(url, poolclass=NullPool, connect_args={'connect_timeout': 2})
    with engine.connect() as connection:
        grants = connection.execute(text('SHOW GRANTS FOR CURRENT_USER()')).scalars().all()
    engine.dispose()
    return [grant for grant in grants if not data_only(grant, url.database)]


def main():
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter())
    log.handlers = [handler]

    # get_config's default: unset means production
    production = os.getenv('APP_ENV', 'production') == 'production'

    # Checked up front: a missing or malformed URL, or one production refuses
    # (no TLS to an external host), would otherwise look like a service that
    # never comes up, and the loop below would wait out the whole timeout.
    try:
        database, redis_ = database_url(), redis_url()
        app_database = database_url(migration=False)
        if database and redis_:
            get_config()
    except ValueError as error:
        log.error(str(error))
        sys.exit(1)
    # In production the grant check below needs DATABASE_URL itself, even
    # beside a migration URL
    required = (('DATABASE_URL', app_database if production else database),
                ('REDIS_URL', redis_))
    missing = [name for name, url in required if url is None]
    if missing:
        log.error(f"Missing required environment variables: {', '.join(missing)}")
        sys.exit(1)
    secrets = [url.password for url in (database, app_database) if url]
    secrets.append(unquote(urlsplit(redis_).password))

    deadline = time.monotonic() + TIMEOUT_SECONDS
    shown = None
    while True:
        errors = [(name, error) for name, error in
                  (('MySQL', mysql_error(database, secrets)),
                   ('Redis', redis_error(redis_, secrets))) if error]
        if not errors:
            log.info('Database and Redis are up')
            break
        # Each error names its cause, which tells a service still booting
        # from one that never will (a wrong password, a missing database).
        waiting = ', '.join(f'{name} ({error})' for name, error in errors)
        if time.monotonic() > deadline:
            log.error(f'Gave up after {TIMEOUT_SECONDS}s waiting for: {waiting}')
            sys.exit(1)
        # Only when it changes, so a long wait doesn't repeat it every second
        if waiting != shown:
            log.info(f'Waiting for: {waiting}')
            shown = waiting
        time.sleep(1)

    # The migrate job checks the app's user too, since the app will connect
    # as it
    if not production:
        return
    try:
        granted = schema_rights(app_database)
    except Exception as error:
        log.error(f"Could not read the grants of DATABASE_URL's user: {describe(error, secrets)}")
        sys.exit(1)
    if granted:
        log.error(
            f"DATABASE_URL's user may do more than read and write rows in its own "
            f"database: {'; '.join(granted)}. Give the app a user with SELECT, INSERT, "
            f"UPDATE and DELETE on its database alone (README, External Database or Redis)")
        sys.exit(1)


if __name__ == '__main__':
    main()
