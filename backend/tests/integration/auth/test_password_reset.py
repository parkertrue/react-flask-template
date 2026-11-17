"""A password reset end to end on real services: the app queues the email
as its Redis user, a worker sends it as the worker's, Mailpit receives it,
and the link it carries sets the password in MySQL and ends the account's
sessions in Redis"""
import os
from urllib.parse import parse_qs, urlsplit

from app.auth.models import TERMS_VERSION
from tests.conftest import link_token
from tests.integration.auth.mailpit import inbox

ADDRESS = 'integration-reset@example.com'
OLD_PASSWORD = 'the old passphrase'
NEW_PASSWORD = 'the new passphrase'


def sign_up(client):
    """The account, and the session sign-up opened"""
    return client.post('/api/auth/register/complete', json={
        'token': link_token(client.application, ADDRESS), 'password': OLD_PASSWORD,
        'terms_version': TERMS_VERSION})


def login(client, password):
    return client.post('/api/auth/login', json={'email': ADDRESS, 'password': password})


def test_reset_through_the_emailed_link(integration_app, integration_client, worker):
    app_name = integration_client.application.config['APP_NAME']
    sign_up(integration_client)
    # Another device, signed in until the reset
    other_device = integration_app.test_client()
    login(other_device, OLD_PASSWORD)

    response = integration_client.post('/api/auth/password-reset', json={'email': ADDRESS})
    worker()
    message, = inbox(ADDRESS)
    link, privacy = [word for word in message['Text'].split() if word.startswith('https://')]
    fragment = parse_qs(urlsplit(link).fragment)
    complete = integration_client.post('/api/auth/password-reset/complete', json={
        'token': fragment['token'][0], 'password': NEW_PASSWORD})
    worker()

    assert response.status_code == 202
    assert message['Subject'] == f'Reset your {app_name} password'
    assert link.startswith(f"{os.environ['APP_URL']}/password-reset/complete#")
    assert set(fragment) == {'token'}
    assert privacy == f"{os.environ['APP_URL']}/privacy"
    assert complete.status_code == 200
    assert other_device.post('/api/auth/refresh').get_json()['error']['code'] == 'AUTH_TOKEN_REVOKED'
    assert login(integration_client, OLD_PASSWORD).status_code == 401
    assert login(integration_client, NEW_PASSWORD).status_code == 200
    assert sorted(m['Subject'] for m in inbox(ADDRESS)) == [
        f'Reset your {app_name} password', f'Your {app_name} password was changed']


def test_an_address_without_an_account_gets_nothing(integration_client, worker):
    response = integration_client.post('/api/auth/password-reset', json={'email': ADDRESS})
    worker()

    assert response.status_code == 202
    assert inbox(ADDRESS) == []
