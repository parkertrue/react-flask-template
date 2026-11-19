"""Timestamps are UTC whatever MySQL's own time zone, which SQLite lacks."""
from datetime import datetime, timedelta, timezone

from tests.conftest import session_token
from sqlalchemy import text


def test_connections_use_utc(integration_db):
    """Without the pin the session follows the server, reported as SYSTEM"""
    with integration_db.engine.connect() as conn:
        assert conn.execute(text('SELECT @@session.time_zone')).scalar() == '+00:00'


def test_timestamp_is_sent_as_utc(integration_client, integration_user):
    """MySQL fills created_at with its own clock; the response says it is UTC"""
    token = session_token(integration_user.id)

    response = integration_client.get(
        '/api/account', headers={'Authorization': f'Bearer {token}'})

    sent = datetime.fromisoformat(response.get_json()['created_at'])
    assert sent.utcoffset() == timedelta(0)
    assert abs(datetime.now(timezone.utc) - sent) < timedelta(minutes=1)
