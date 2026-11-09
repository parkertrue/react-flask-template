"""The breached-password check, against a faked Pwned Passwords API"""
import hashlib
import io
import socket
import urllib.error

import pytest

from app.utils import breached
from app.utils.breached import is_breached

PASSWORD = 'correct horse battery staple'
DIGEST = hashlib.sha1(PASSWORD.encode()).hexdigest().upper()
API = 'https://pwned.test/range/'


class FakeApi:
    """Stands in for urlopen: records each request, answers with body or
    raises error"""

    def __init__(self):
        self.requests = []
        self.body = ''
        self.error = None

    def __call__(self, request, timeout):
        self.requests.append((request, timeout))
        if self.error:
            raise self.error
        return io.BytesIO(self.body.encode('ascii'))


@pytest.fixture
def api(app, monkeypatch):
    fake = FakeApi()
    monkeypatch.setattr(breached.urllib.request, 'urlopen', fake)
    monkeypatch.setitem(app.config, 'PWNED_PASSWORDS_URL', API)
    return fake


def answer(*lines):
    return '\r\n'.join(lines)


def test_a_breached_password(api):
    api.body = answer('0018A45C4D1DEF81644B54AB7F969B88D65:1', f'{DIGEST[5:]}:3861493')

    assert is_breached(PASSWORD) is True


def test_a_password_not_in_the_answer(api):
    api.body = answer('0018A45C4D1DEF81644B54AB7F969B88D65:1')

    assert is_breached(PASSWORD) is False


def test_padding_does_not_count(api):
    """Add-Padding fills the answer with decoys whose count is 0"""
    api.body = answer(f'{DIGEST[5:]}:0')

    assert is_breached(PASSWORD) is False


def test_only_the_first_five_characters_of_the_hash_leave(api):
    is_breached(PASSWORD)

    (request, timeout), = api.requests
    assert request.full_url == API + DIGEST[:5]
    assert PASSWORD not in request.full_url
    assert DIGEST[5:] not in request.full_url
    assert request.get_header('Add-padding') == 'true'
    assert timeout == breached.TIMEOUT_SECONDS


@pytest.mark.parametrize('error', [
    urllib.error.URLError('unreachable'),
    urllib.error.HTTPError(API, 503, 'Service Unavailable', {}, None),
    socket.timeout('timed out'),
    ConnectionResetError(),
], ids=['unreachable', 'a 503', 'timed out', 'reset'])
def test_fails_open_and_logs_why(api, logged, error):
    """An outage must not stop sign-up: the password goes through, logged"""
    api.error = error

    assert is_breached(PASSWORD) is False
    line, = [line for line in logged() if line['message'] == 'breach_check_failed']
    assert line['reason'] == type(error).__name__
    assert PASSWORD not in str(line)


def test_off_without_a_url(app, monkeypatch):
    """Outside production unless set: tests and dev call no third party"""
    calls = []
    monkeypatch.setattr(breached.urllib.request, 'urlopen', lambda *a, **kw: calls.append(a))
    monkeypatch.setitem(app.config, 'PWNED_PASSWORDS_URL', None)

    assert is_breached(PASSWORD) is False
    assert calls == []
