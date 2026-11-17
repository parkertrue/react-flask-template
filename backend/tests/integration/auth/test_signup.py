"""Sign-up end to end on real services: the app queues the email as its
Redis user, a worker sends it as the worker's, Mailpit receives it, and the
link it carries makes the account in MySQL"""
import os
from urllib.parse import parse_qs, urlsplit

from app.auth.models import TERMS_VERSION
from tests.conftest import link_token
from tests.integration.auth.mailpit import inbox

ADDRESS = 'integration-signup@example.com'


def test_sign_up_through_the_emailed_link(integration_client, worker):
    response = integration_client.post('/api/auth/register', json={'email': ADDRESS})
    worker()

    message, = inbox(ADDRESS)
    link, privacy = [word for word in message['Text'].split() if word.startswith('https://')]
    fragment = parse_qs(urlsplit(link).fragment)
    complete = integration_client.post('/api/auth/register/complete', json={
        'token': fragment['token'][0], 'password': 'TestPassword123',
        'terms_version': TERMS_VERSION})
    account = integration_client.get('/api/account', headers={
        'Authorization': f"Bearer {complete.get_json()['access_token']}"})

    assert response.status_code == 202
    assert message['Subject'] == f"Finish signing up for {integration_client.application.config['APP_NAME']}"
    assert link.startswith(f"{os.environ['APP_URL']}/signup/complete#")
    assert set(fragment) == {'token'}
    assert privacy == f"{os.environ['APP_URL']}/privacy"
    assert complete.status_code == 200
    assert complete.get_json()['email'] == ADDRESS
    assert account.get_json()['email'] == ADDRESS


def test_a_registered_address_is_told_so(integration_client, worker):
    integration_client.post('/api/auth/register/complete', json={
        'token': link_token(integration_client.application, ADDRESS), 'password': 'TestPassword123',
        'terms_version': TERMS_VERSION})

    integration_client.post('/api/auth/register', json={'email': ADDRESS})
    worker()

    message, = inbox(ADDRESS)
    assert message['Subject'] == f"You already have a {integration_client.application.config['APP_NAME']} account"
