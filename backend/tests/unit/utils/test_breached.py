"""The breached-password check: what it sends and how it reads the answer
against a faked urlopen, its deadline and decoding through a real socket"""
import hashlib
import io
import socket
import threading
import time
import urllib.error
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

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


def test_it_introduces_itself_by_the_app_s_name(app, api, monkeypatch):
    """Pwned Passwords asks each client to name its app, so one app's
    misuse never gets every app built from the template blocked"""
    monkeypatch.setitem(app.config, 'APP_NAME', 'Another App')

    is_breached(PASSWORD)

    (request, _), = api.requests
    assert request.get_header('User-agent') == 'Another App'


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


class LocalApi(ThreadingHTTPServer):
    """A Pwned Passwords stand-in on a real socket: answers each request
    with body, sent all at once or a byte at a time every `trickle` seconds
    until the test ends"""
    body = b''
    trickle = 0.0

    def __init__(self):
        super().__init__(('127.0.0.1', 0), _Answer)
        self.done = threading.Event()


class _Answer(BaseHTTPRequestHandler):
    server: LocalApi

    def do_GET(self):
        self.send_response(200)
        self.send_header('Content-Length', str(len(self.server.body)))
        self.end_headers()
        if not self.server.trickle:
            self.wfile.write(self.server.body)
            return
        for byte in self.server.body:
            if self.server.done.wait(self.server.trickle):
                return
            self.wfile.write(bytes([byte]))
            self.wfile.flush()

    def log_message(self, *args):
        pass


@pytest.fixture
def local_api(app, monkeypatch):
    server = LocalApi()
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    monkeypatch.setitem(
        app.config, 'PWNED_PASSWORDS_URL', f'http://127.0.0.1:{server.server_address[1]}/range/')
    yield server
    server.done.set()
    server.shutdown()
    server.server_close()


def test_a_breached_password_through_a_real_socket(local_api):
    local_api.body = answer(f'{DIGEST[5:]}:3861493').encode('ascii')

    assert is_breached(PASSWORD) is True


def test_a_slow_answer_gives_up_within_the_deadline(local_api, logged):
    """A socket's timeout bounds each read: an answer trickling a byte at a
    time would otherwise hold the request as long as the server likes"""
    local_api.body = answer(f'{DIGEST[5:]}:3861493').encode('ascii')
    local_api.trickle = 0.5
    started = time.monotonic()

    breached_found = is_breached(PASSWORD)

    assert time.monotonic() - started < 3
    assert breached_found is False
    line, = [line for line in logged() if line['message'] == 'breach_check_failed']
    assert line['reason'] == 'TimeoutError'


def test_a_garbled_answer_fails_open(local_api, logged):
    local_api.body = 'é:1'.encode('latin-1')

    assert is_breached(PASSWORD) is False
    line, = [line for line in logged() if line['message'] == 'breach_check_failed']
    assert line['reason'] == 'UnicodeDecodeError'
