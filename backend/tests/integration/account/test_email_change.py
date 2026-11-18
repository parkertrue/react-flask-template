"""An email change end to end on real services: the app queues the link as
its Redis user, a worker sends it as the worker's, Mailpit receives it, the
link moves the account in MySQL, the old address is told, and its link
moves the account back"""
from urllib.parse import parse_qs, urlsplit

from app.auth.models import TERMS_VERSION
from tests.conftest import link_token
from tests.integration.mailpit import inbox

OLD = 'integration-old@example.com'
NEW = 'integration-new@example.com'
PASSWORD = 'an integration passphrase'


def emailed_token(address):
    message, = inbox(address)
    link = next(word for word in message['Text'].split() if word.startswith('https://'))
    return message['Subject'], urlsplit(link).path, parse_qs(urlsplit(link).fragment)['token'][0]


def test_change_then_undo(integration_client, worker):
    app_name = integration_client.application.config['APP_NAME']
    signed_up = integration_client.post('/api/auth/register/complete', json={
        'token': link_token(integration_client.application, OLD), 'password': PASSWORD,
        'terms_version': TERMS_VERSION})
    headers = {'Authorization': f"Bearer {signed_up.get_json()['access_token']}"}

    asked = integration_client.post('/api/account/email', headers=headers,
                                    json={'email': NEW, 'password': PASSWORD})
    worker()
    subject, path, token = emailed_token(NEW)
    changed = integration_client.post('/api/account/email/complete', json={'token': token})
    worker()
    notice_subject, undo_path, undo = emailed_token(OLD)
    account = integration_client.get('/api/account', headers=headers)
    undone = integration_client.post('/api/account/email/undo', json={'token': undo})

    assert asked.status_code == 202
    assert (subject, path) == (f'Confirm your new {app_name} email', '/account/email/complete')
    assert changed.get_json() == {'email': NEW}
    assert account.get_json()['email'] == NEW
    assert (notice_subject, undo_path) == (f'Your {app_name} email was changed', '/account/email/undo')
    assert undone.get_json() == {'email': OLD}
    assert integration_client.post('/api/auth/login', json={
        'email': OLD, 'password': PASSWORD}).status_code == 200
