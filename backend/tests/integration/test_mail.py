"""Sending email to a real SMTP server: Mailpit (docker-compose.test.yml),
read back through its API"""
from email.utils import parseaddr
from urllib.parse import quote

import pytest
from flask import current_app

from app.utils.mail import send_email
from tests.integration.mailpit import mailpit

ADDRESS = 'integration-mail@example.com'


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
    # The configured sender, which a new app renames (test_env_literals.py)
    sender = parseaddr(current_app.config['EMAIL_FROM'])[1]
    assert (message['Subject'], message['From']['Address'], message['To'][0]['Address']) == (
        'Integration hello', sender, ADDRESS)
    assert message['Text'] == 'Sent over SMTP.\r\n'
