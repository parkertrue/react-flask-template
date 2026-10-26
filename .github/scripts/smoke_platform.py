"""Check the platform layout (.github/smoke/platform.yml) from its load balancer's side.

CI's Platform smoke job runs this against the backend and a behind-proxy
nginx sharing one network namespace, as on ECS or Kubernetes. It plays the
load balancer: plain HTTP to nginx's published port, with the X-Forwarded-*
headers a balancer adds. Every failed check is printed, then it exits 1.
"""
import http.client
import json
import subprocess
import sys
import uuid

PORT = 8081
SERVER_NAME = 'localhost'  # nginx/Dockerfile's NGINX_SERVER_NAME
COMPOSE = ['docker', 'compose', '--env-file', '.env.test', '-f', 'docker-compose.test.yml',
           '-f', '.github/smoke/platform.yml', '--profile', 'platform']
CLIENT = '203.0.113.7'
# The balancer appends the address it saw; whatever the client sent comes first
FORWARDED_FOR = f'198.51.100.9, {CLIENT}'
PAGE_HEADERS = {
    'Strict-Transport-Security': 'max-age=31536000; includeSubDomains',
    'X-Frame-Options': 'DENY',
    'X-Content-Type-Options': 'nosniff',
    'Content-Security-Policy': "default-src 'self'; script-src 'self'; style-src 'self'; "
                               "img-src 'self'; font-src 'self'; connect-src 'self'; "
                               "frame-ancestors 'none'; base-uri 'self'; form-action 'self';",
}

failures = []


def check(name, ok, detail=''):
    print(f"{'ok  ' if ok else 'FAIL'} {name}{f': {detail}' if not ok else ''}")
    if not ok:
        failures.append(name)


def request(method, path, host=SERVER_NAME, proto='https', body=None, headers=None):
    """One request as the balancer forwards it: (status, headers, body), status None if dropped"""
    conn = http.client.HTTPConnection('127.0.0.1', PORT, timeout=10)
    sent = {'Host': host, 'X-Forwarded-Proto': proto, 'X-Forwarded-For': FORWARDED_FOR,
            **(headers or {})}
    try:
        conn.request(method, path, body=body, headers=sent)
        response = conn.getresponse()
        return response.status, response.headers, response.read()
    except (http.client.RemoteDisconnected, ConnectionResetError):
        return None, {}, b''
    finally:
        conn.close()


def log_lines(service):
    out = subprocess.run([*COMPOSE, 'logs', '--no-log-prefix', '--no-color', service],
                         capture_output=True, text=True, check=True).stdout
    return [json.loads(line) for line in out.splitlines() if line.startswith('{')]


status, _, body = request('GET', '/api/health')
check('health answers for the server name', (status, body) == (200, b'{"status":"ok"}\n'),
      f'{status} {body!r}')

# A load balancer's health check names the target's own address
status, _, _ = request('GET', '/api/health', host='10.0.0.5')
check("health answers the balancer's check by address", status == 200, status)

status, _, _ = request('GET', '/', host='attacker.example')
check('any other host is dropped', status is None, status)

status, headers, _ = request('GET', '/')
check('the page is served', status == 200, status)
for name, value in PAGE_HEADERS.items():
    check(f'the page sends {name}', headers.get(name) == value, headers.get(name))

status, headers, _ = request('GET', '/account', proto='http')
check('plain HTTP is redirected to HTTPS',
      (status, headers.get('Location')) == (301, f'https://{SERVER_NAME}/account'),
      f"{status} {headers.get('Location')}")

status, _, body = request('POST', '/api/auth/login', body=b'x' * (17 * 1024),
                          headers={'Content-Type': 'application/json'})
check('a body over 16 KB gets a JSON 413',
      status == 413 and json.loads(body)['error']['code'] == 'PAYLOAD_TOO_LARGE',
      f'{status} {body[:100]!r}')

# The client's address, as nginx and the backend's rate limits see it. A new
# account each run, so reruns stay under its login limit.
marker = f'smoke-{uuid.uuid4().hex}'
status, _, _ = request(
    'POST', '/api/auth/login', headers={'Content-Type': 'application/json', 'User-Agent': marker},
    body=json.dumps({'email': f'{marker}@example.com', 'password': 'Wrong-pass1'}).encode())
check('a failed login is refused', status == 401, status)
access = [line for line in log_lines('platform-nginx') if line.get('user_agent') == marker]
check('nginx logs the login once', len(access) == 1, access)
if access:
    check("nginx logs the balancer's client address", access[0]['ip'] == CLIENT, access[0]['ip'])
    events = [line for line in log_lines('platform-backend')
              if line.get('request_id') == access[0]['request_id']
              and line['message'] == 'login_failed']
    check('the backend logs login_failed once', len(events) == 1, events)
    if events:
        check("the backend's rate limits key on the client's address",
              events[0]['ip'] == CLIENT, events[0]['ip'])

if failures:
    sys.exit(f'{len(failures)} check(s) failed')
