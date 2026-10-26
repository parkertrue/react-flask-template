"""Block until MySQL and Redis accept connections, or exit 1 after a timeout.

Run by entrypoint.sh before the container's command (gunicorn, or the
migrate service's `flask db upgrade`) and by run_dev.sh (local dev). Reads
the URLs as app/config.py does, so it logs in as the app will. Logs as the
app does, one JSON object per line on stdout, so every line the backend
container writes parses alike.
"""
import logging
import sys
import time
from urllib.parse import unquote, urlsplit

import redis
from sqlalchemy import create_engine
from sqlalchemy.pool import NullPool

from app.config import database_url, redis_url
from app.utils.log import JsonFormatter

log = logging.getLogger('wait_for_services')
log.setLevel(logging.INFO)

# Matches the backend healthcheck's start_period (docker-compose.yml and
# docker-compose.test.yml), which covers this wait: change them together.
TIMEOUT_SECONDS = 60


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


def main():
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter())
    log.handlers = [handler]

    # Checked up front: a missing or malformed URL would otherwise look like
    # a service that never comes up, and the loop below would wait out the
    # whole timeout.
    try:
        database, redis_ = database_url(), redis_url()
    except ValueError as error:
        log.error(str(error))
        sys.exit(1)
    missing = [name for name, url in (('DATABASE_URL', database), ('REDIS_URL', redis_))
               if url is None]
    if missing:
        log.error(f"Missing required environment variables: {', '.join(missing)}")
        sys.exit(1)
    secrets = [database.password, unquote(urlsplit(redis_).password)]

    deadline = time.monotonic() + TIMEOUT_SECONDS
    shown = None
    while True:
        errors = [(name, error) for name, error in
                  (('MySQL', mysql_error(database, secrets)),
                   ('Redis', redis_error(redis_, secrets))) if error]
        if not errors:
            log.info('Database and Redis are up')
            return
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


if __name__ == '__main__':
    main()
