"""Sending email to a real SMTP server: Mailpit (docker-compose.test.yml),
read back through its API"""
import json
import os
import urllib.request
from urllib.parse import quote

import pytest

from app.utils.mail import send_email

ADDRESS = 'integration-mail@example.com'


def mailpit(path, method='GET'):
    request = urllib.request.Request(os.environ['MAILPIT_API_URL'] + path, method=method)
    with urllib.request.urlopen(request, timeout=5) as response:
        return json.loads(response.read()) if method == 'GET' else None


@pytest.fixture
def inbox(integration_app):
    """Mailpit's messages to ADDRESS, emptied before and after the test"""
    mailpit('/messages', method='DELETE')
    with integration_app.app_context():
        yield lambda: mailpit(f'/search?query={quote(f"to:{ADDRESS}")}')['messages']
    mailpit('/messages', method='DELETE')


def test_mailpit_receives_the_email(inbox):
    send_email(ADDRESS, 'Integration hello', 'Sent over SMTP.\n')

    summary, = inbox()
    message = mailpit(f"/message/{summary['ID']}")
    assert (message['Subject'], message['From']['Address'], message['To'][0]['Address']) == (
        'Integration hello', 'no-reply@app.localhost', ADDRESS)
    assert message['Text'] == 'Sent over SMTP.\r\n'
