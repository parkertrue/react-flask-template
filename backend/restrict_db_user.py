"""Leave the app's MySQL user with data rights only, once migrations are done.

The MySQL image grants the app's user every privilege on the database. The
migrate service in docker-compose.yml runs this as root after
`flask db upgrade`, narrowing that user to what the running app needs, so a
compromised backend can read and write rows but never drop or alter tables.
Safe to run on every deploy.

Reads DB_HOST/PORT/NAME and the admin DB_USER/DB_PASSWORD like
app/config.py; APP_DB_USER names the user to restrict.
"""
import logging
import os
import re
import sys

import pymysql

from app.utils.log import JsonFormatter

# JSON on stdout, like every other line the backend image writes
log = logging.getLogger('restrict_db_user')
log.setLevel(logging.INFO)

DATA_PRIVILEGES = 'SELECT, INSERT, UPDATE, DELETE'
# Every other database-level privilege that the image's GRANT ALL included
SCHEMA_PRIVILEGES = (
    'ALTER, ALTER ROUTINE, CREATE, CREATE ROUTINE, CREATE TEMPORARY TABLES, '
    'CREATE VIEW, DROP, EVENT, EXECUTE, INDEX, LOCK TABLES, REFERENCES, '
    'SHOW VIEW, TRIGGER'
)


def main():
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter())
    log.handlers = [handler]

    database = os.environ['DB_NAME']
    # Identifiers cannot be passed as query parameters, so only allow names
    # that are safe to put between backticks
    if not re.fullmatch(r'\w+', database):
        log.error(f'Refusing unexpected database name: {database!r}')
        sys.exit(1)
    app_user = os.environ['APP_DB_USER']
    # In GRANT and REVOKE, `_` in a database name is a wildcard. The MySQL
    # image escapes it when it grants ALL, so the grant row to narrow is
    # `app\_db`; a statement on `app_db` would touch a different row.
    escaped = database.replace('_', r'\_')

    connection = pymysql.connect(
        host=os.environ['DB_HOST'],
        port=int(os.getenv('DB_PORT', '3306')),
        user=os.environ['DB_USER'],
        password=os.environ['DB_PASSWORD'],
    )
    with connection, connection.cursor() as cursor:
        # Grant before revoking: a backend still serving from the previous
        # deploy keeps its data access throughout. IF EXISTS makes revoking
        # privileges already gone (every run after the first) a no-op.
        cursor.execute(
            f"GRANT {DATA_PRIVILEGES} ON `{escaped}`.* TO %s@'%%'", (app_user,))
        cursor.execute(
            f"REVOKE IF EXISTS {SCHEMA_PRIVILEGES} ON `{escaped}`.* FROM %s@'%%'",
            (app_user,))
    log.info(f'{app_user} restricted to {DATA_PRIVILEGES} on {database}')


if __name__ == '__main__':
    main()
