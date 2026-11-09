"""Sign-up end to end on real services: the app queues the email as its
Redis user, a worker sends it as the worker's, Mailpit receives it, and the
link it carries makes the account in MySQL"""
import json
import os
import urllib.request
from urllib.parse import parse_qs, quote, urlsplit

import pytest
from dramatiq import Worker

from app import create_app
from app.auth.models import TERMS_VERSION
from app.utils.jobs import QUEUE_NAME
from tests.conftest import link_token

ADDRESS = 'integration-signup@example.com'


def mailpit(path, method='GET'):
    request = urllib.request.Request(os.environ['MAILPIT_API_URL'] + path, method=method)
    with urllib.request.urlopen(request, timeout=5) as response:
        return json.loads(response.read()) if method == 'GET' else None


@pytest.fixture
def worker(integration_app, integration_db, integration_redis, monkeypatch):
    """Runs the queued jobs as the worker container does: its own app, as
    the worker's Redis user"""
    mailpit('/messages', method='DELETE')
    monkeypatch.setenv('REDIS_URL', os.environ['REDIS_WORKER_URL'])
    # The app's password, which would replace the URL's; the container gets none
    monkeypatch.delenv('REDIS_PASSWORD')
    worker_app = create_app()

    def run():
        broker = worker_app.extensions['jobs_broker']
        running = Worker(broker, worker_timeout=100)
        running.start()
        broker.join(QUEUE_NAME)
        running.join()
        running.stop()
    yield run
    worker_app.extensions['jobs_broker'].close()
    mailpit('/messages', method='DELETE')


def inbox():
    summaries = mailpit(f'/search?query={quote(f"to:{ADDRESS}")}')['messages']
    return [mailpit(f"/message/{summary['ID']}") for summary in summaries]


def test_sign_up_through_the_emailed_link(integration_client, worker):
    response = integration_client.post('/api/auth/register', json={'email': ADDRESS})
    worker()

    message, = inbox()
    link, = [word for word in message['Text'].split() if word.startswith('https://')]
    fragment = parse_qs(urlsplit(link).fragment)
    complete = integration_client.post('/api/auth/register/complete', json={
        'token': fragment['token'][0], 'password': 'TestPassword123',
        'terms_version': TERMS_VERSION})
    account = integration_client.get('/api/account', headers={
        'Authorization': f"Bearer {complete.get_json()['access_token']}"})

    assert response.status_code == 202
    assert message['Subject'] == 'Finish signing up'
    assert link.startswith(f"{os.environ['APP_URL']}/register/complete#")
    assert fragment['email'] == [ADDRESS]
    assert complete.status_code == 200
    assert account.get_json()['email'] == ADDRESS


def test_a_registered_address_is_told_so(integration_client, worker):
    integration_client.post('/api/auth/register/complete', json={
        'token': link_token(integration_client.application, ADDRESS), 'password': 'TestPassword123',
        'terms_version': TERMS_VERSION})

    integration_client.post('/api/auth/register', json={'email': ADDRESS})
    worker()

    message, = inbox()
    assert message['Subject'] == 'You already have an account'
