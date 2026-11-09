"""A restored backup on real MySQL: ids are handed out again from where the
dump left off, and a token of an account the restore removed must not work
as the account that takes its id next."""
from sqlalchemy import text

from app.auth.models import User
from tests.conftest import register

PASSWORD = 'TestPassword123'


def _register(client, email):
    return register(client, email, PASSWORD)


def test_a_token_of_an_account_a_restore_removed(
        integration_client, integration_db, integration_redis):
    assert _register(integration_client, 'before-restore@example.com').status_code == 200
    # Created a day earlier, so the next account cannot share its second
    integration_db.session.execute(
        text('UPDATE users SET created_at = created_at - INTERVAL 1 DAY'))
    integration_db.session.commit()
    login = integration_client.post('/api/auth/login', json={
        'email': 'before-restore@example.com', 'password': PASSWORD}).get_json()
    old_id = integration_db.session.scalar(text('SELECT id FROM users'))
    # The restore: the row is gone and the counter is back where the dump left it
    integration_db.session.execute(text('DELETE FROM users'))
    integration_db.session.execute(text(f'ALTER TABLE users AUTO_INCREMENT = {old_id}'))
    integration_db.session.commit()
    # From another browser: signing up logs in, and its cookie would replace
    # the one under test
    assert _register(integration_client.application.test_client(),
                     'after-restore@example.com').status_code == 200
    integration_db.session.expire_all()
    assert integration_db.session.get(User, old_id).email == 'after-restore@example.com'

    account = integration_client.get(
        '/api/account', headers={'Authorization': f"Bearer {login['access_token']}"})
    # The refresh cookie from the login; IntegrationConfig checks no CSRF value
    refresh = integration_client.post('/api/auth/refresh')

    assert [account.status_code, refresh.status_code] == [401, 401]
