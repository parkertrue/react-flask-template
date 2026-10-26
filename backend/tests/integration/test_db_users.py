"""The database users db/init/01-app-user.sh leaves, against real MySQL.

The app connects as DATABASE_URL's user, which may read and write rows but
never change the schema, so a compromised backend cannot drop or alter a
table. The migration user owns the schema; this suite's own app connects as
it (MIGRATION_DATABASE_URL), since integration_db creates the tables.
"""
import os

import pytest
from sqlalchemy import create_engine, make_url, text
from sqlalchemy.exc import OperationalError

import wait_for_services as wait

# MySQL's ER_TABLEACCESS_DENIED_ERROR: a command the user may not run
ACCESS_DENIED = 1142


@pytest.fixture
def app_user():
    """A connection as the app's own user, which the E2E backend gets"""
    engine = create_engine(os.environ['DATABASE_URL'])
    with engine.connect() as connection:
        yield connection
    engine.dispose()


def test_app_user_has_data_rights_only(app_user):
    url = make_url(os.environ['DATABASE_URL'])
    # `_` in a database name is a GRANT wildcard, which the script escapes
    database = url.database.replace('_', '\\_')
    grants = app_user.execute(text('SHOW GRANTS FOR CURRENT_USER()')).scalars().all()

    assert grants == [
        f'GRANT USAGE ON *.* TO `{url.username}`@`%`',
        f'GRANT SELECT, INSERT, UPDATE, DELETE ON `{database}`.* TO `{url.username}`@`%`',
    ]


@pytest.mark.parametrize('statement', [
    'CREATE TABLE probe (id INT)',
    'ALTER TABLE users ADD COLUMN probe INT',
    'CREATE INDEX probe ON users (created_at)',
    'DROP TABLE users',
])
def test_app_user_cannot_change_the_schema(integration_db, app_user, statement):
    with pytest.raises(OperationalError) as exc_info:
        app_user.execute(text(statement))

    assert exc_info.value.orig.args[0] == ACCESS_DENIED


def test_app_user_reads_and_writes_rows(integration_db, app_user):
    app_user.execute(text(
        "INSERT INTO users (email, password_hash, terms_version, terms_accepted_at) "
        "VALUES ('probe@example.com', 'x', 1, UTC_TIMESTAMP())"))
    app_user.execute(text("UPDATE users SET password_hash = 'y' WHERE email = 'probe@example.com'"))
    hashes = app_user.execute(text('SELECT password_hash FROM users')).scalars().all()
    app_user.execute(text("DELETE FROM users WHERE email = 'probe@example.com'"))
    app_user.commit()

    assert hashes == ['y']
    assert app_user.execute(text('SELECT COUNT(*) FROM users')).scalar() == 0


def test_the_production_start_check_passes_the_app_user_alone():
    """wait_for_services.py refuses a DATABASE_URL user that owns the schema"""
    app_user = wait.schema_rights(make_url(os.environ['DATABASE_URL']))
    owner = wait.schema_rights(make_url(os.environ['MIGRATION_DATABASE_URL']))

    assert app_user == []
    assert [grant.partition(' ON ')[0] for grant in owner] == ['GRANT ALL PRIVILEGES']
