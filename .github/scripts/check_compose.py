"""Fail when the compose files' copies of the same settings disagree.

CI's Compose job runs this. The test stack copies production's hardening, so
that E2E catches a service an image change breaks under it, and all three
stacks copy the Redis ACL and mount the database's init scripts, which create
the app's data-only user; nothing else compares the copies.

It also pins, in production (one line per rule: add a new one as a line):
- ports published on IPv4 only;
- db without a binary log;
- Redis compacting its on-disk log at 1 MB, which otherwise keeps deleted
  values, such as a job's recipient, until 64 MB;
- every secret required (`:?`) wherever the backend, migrate and the worker
  use it, so a missing one stops compose rather than starting Redis on an
  empty password (read from the file itself, since `config` resolves it);
- backend, migrate, worker and nginx read-only;
- every capability dropped by the services that run the backend image;
- the mail server's password on the worker alone;
- the backend waiting for `migrate` to succeed, which a plain
  `docker compose up` (README, Build and Start) relies on; deploy.sh runs
  migrate itself.
And in production and the test stack:
- the worker outlasting its wait for running jobs when stopped, and
  checking the file it writes once ready, both read from
  backend/app/utils/jobs.py.

Each file is read as `docker compose config` resolves it, anchors and
merges applied.
"""
import json
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
# db/init, where every stack's db service must find its init scripts
INIT_SCRIPTS = ROOT / 'db' / 'init'
# Where the worker's wait for running jobs and its ready file are set
JOBS = ROOT / 'backend' / 'app' / 'utils' / 'jobs.py'
# Docker's stop_grace_period for a service that sets none
DEFAULT_STOP_GRACE = '10s'

# The hardening each test service must share with its production namesake
HARDENING = ('security_opt', 'cap_drop', 'cap_add', 'read_only', 'pids')

# The services whose root filesystem production keeps read-only. db and redis
# stay writable: their entrypoints write on first start (DECISIONS.md).
READ_ONLY = ('backend', 'migrate', 'worker', 'nginx')
# The services that run the backend image, which needs no capability
BACKEND_IMAGE = ('backend', 'migrate', 'worker')
# What only the worker, which sends email, may be given
WORKER_ONLY = ('EMAIL_URL', 'EMAIL_PASSWORD')
# The secrets production must refuse to run without. Outside the bundled db
# and redis services, every use must be required (${NAME:?...}); their own
# copies stay plain, since compose requires a :? even in a service whose
# profile is off, which would make an external database or Redis set them.
REQUIRED_SECRETS = (
    'SECRET_KEY', 'DB_PASSWORD', 'DB_MIGRATION_PASSWORD', 'REDIS_PASSWORD',
    'REDIS_WORKER_PASSWORD')
BUNDLED = ('db', 'redis')
# The size at which production's Redis compacts its on-disk log, as
# docs/personal-data.md tells users
AOF_REWRITE_MIN_SIZE = '1mb'


def config(*args):
    out = subprocess.run(
        ['docker', 'compose', *args, 'config', '--format', 'json'],
        check=True, capture_output=True, text=True,
    ).stdout
    return json.loads(out)['services']


def hardening(service):
    # Production sets its pids limit with its other limits, under deploy;
    # the test stack, without deploy, sets pids_limit
    limits = service.get('deploy', {}).get('resources', {}).get('limits', {})
    settings = {key: service.get(key) for key in HARDENING[:-1]}
    settings['pids'] = service.get('pids_limit', limits.get('pids'))
    for key in ('security_opt', 'cap_drop', 'cap_add'):
        settings[key] = sorted(settings[key] or [])
    settings['read_only'] = bool(settings['read_only'])
    return settings


def acl(redis):
    """The ACL arguments, from the first --user to the last -@ category, with
    the password (each env file's own) masked"""
    command = redis['command']
    start = command.index('--user')
    end = max(i for i, arg in enumerate(command) if arg.startswith('-@')) + 1
    return ['>password' if arg.startswith('>') else arg for arg in command[start:end]]


def flag_value(service, flag):
    """The value after flag in a service's command, or None"""
    command = service.get('command') or []
    return command[command.index(flag) + 1] if flag in command[:-1] else None


def outside_bundled_services(text):
    """The production file's lines, without the db and redis services'"""
    kept, skipping = [], False
    for line in text.splitlines():
        service = re.fullmatch(r'  ([\w-]+):\s*', line)
        if service or (line and not line.startswith(' ')):
            skipping = bool(service) and service.group(1) in BUNDLED
        if not skipping:
            kept.append(line)
    return '\n'.join(kept)


def secret_problems(text):
    used = outside_bundled_services(text)
    for name in REQUIRED_SECRETS:
        uses = re.findall(r'\$\{' + name + r'(:\?|\W)', used)
        if not uses:
            yield f'{name}: production uses it nowhere outside the db and redis services'
        elif any(use != ':?' for use in uses):
            yield f'{name}: production uses it without requiring it (${{{name}:?...}})'


def init_mounts(db):
    """What the db service mounts as the MySQL image's init scripts"""
    return [(Path(volume['source']), volume.get('read_only', False))
            for volume in db.get('volumes', [])
            if volume['target'] == '/docker-entrypoint-initdb.d']


def worker_settings():
    """The worker's wait for running jobs when stopped, in seconds, and the
    name of the file it writes once ready, as jobs.py sets them"""
    source = JOBS.read_text(encoding='utf-8')
    drain = re.search(r'^SHUTDOWN_TIMEOUT = timedelta\(seconds=(\d+)\)$', source, re.MULTILINE)
    ready = re.search(r"^READY_FILE = .* / '([^']+)'$", source, re.MULTILINE)
    if drain is None or ready is None:
        sys.exit(f'{JOBS}: SHUTDOWN_TIMEOUT or READY_FILE is not set as this script reads it')
    return int(drain[1]), ready[1]


def seconds(duration):
    """A compose duration ('30s', '1m30s') in seconds"""
    units = {'h': 3600, 'm': 60, 's': 1}
    return sum(int(amount) * units[unit] for amount, unit in re.findall(r'(\d+)([hms])', duration))


def worker_problems(stack, worker, drain, ready):
    grace = worker.get('stop_grace_period') or DEFAULT_STOP_GRACE
    if seconds(grace) <= drain:
        yield f'worker: {stack} stops it after {grace}, within its {drain}s wait for running jobs'
    if not any(arg.endswith(f'/{ready}') for arg in worker.get('healthcheck', {}).get('test', [])):
        yield f'worker: the {stack} healthcheck does not test for {ready}, the file it writes once ready'


def problems(prod, test, dev):
    for name, service in prod.items():
        if name not in test:
            yield f'{name}: in production, missing from the test stack'
            continue
        ours, theirs = hardening(service), hardening(test[name])
        for key in HARDENING:
            if ours[key] != theirs[key]:
                yield f'{name}: {key} is {ours[key]!r} in production, {theirs[key]!r} in test'
    for stack, services in (('test', test), ('dev', dev)):
        if acl(services['redis']) != acl(prod['redis']):
            yield f"redis: the ACL in {stack} differs from production's"
    for stack, services in (('production', prod), ('test', test), ('dev', dev)):
        if init_mounts(services['db']) != [(INIT_SCRIPTS, True)]:
            yield f'db: {stack} does not mount db/init read-only as its init scripts'
    # A port without a host address listens on [::] too, where Docker's proxy
    # relays every IPv6 visitor from one address (DECISIONS.md)
    for name, service in prod.items():
        for port in service.get('ports', []):
            if port.get('host_ip') != '0.0.0.0':
                where = port.get('host_ip') or 'every address, IPv6 included'
                yield f"{name}: port {port['target']} is published on {where}, not 0.0.0.0"
    # The test stack copies read_only, so this alone keeps both
    for name in READ_ONLY:
        if not prod[name].get('read_only'):
            yield f'{name}: production does not run with a read-only root filesystem'
    for name in BACKEND_IMAGE:
        if prod[name].get('cap_drop') != ['ALL']:
            yield f'{name}: production does not drop every capability'
    for name, service in prod.items():
        given = [var for var in WORKER_ONLY if var in (service.get('environment') or {})]
        if given and name != 'worker':
            yield f"{name}: gets {', '.join(given)}, which only the worker may hold"
    if '--disable-log-bin' not in prod['db'].get('command', []):
        yield 'db: production does not run with --disable-log-bin'
    if flag_value(prod['redis'], '--auto-aof-rewrite-min-size') != AOF_REWRITE_MIN_SIZE:
        yield f'redis: production does not compact its on-disk log at {AOF_REWRITE_MIN_SIZE}'
    drain, ready = worker_settings()
    for stack, services in (('production', prod), ('test', test)):
        yield from worker_problems(stack, services['worker'], drain, ready)
    yield from secret_problems((ROOT / 'docker-compose.yml').read_text(encoding='utf-8'))
    migrate = prod['backend'].get('depends_on', {}).get('migrate', {})
    if migrate.get('condition') != 'service_completed_successfully':
        yield 'backend: production does not wait for migrate to complete successfully'


def main():
    prod = config('--env-file', '.env.prod.example')
    test = config('--env-file', '.env.test', '-f', 'docker-compose.test.yml', '--profile', 'e2e')
    dev = config('--env-file', '.env.dev', '-f', 'docker-compose.dev.yml')
    found = list(problems(prod, test, dev))
    sys.stdout.write(''.join(f'{p}\n' for p in found))
    if found:
        sys.exit(f'{len(found)} compose setting(s) differ')
    sys.stdout.write(f'{len(prod)} services, the Redis ACL and the db init scripts match, '
                     'ports are IPv4 only, the db keeps no binary log, Redis compacts its log at 1 MB, '
                     'every secret is required, '
                     'the backend, migrate, worker and nginx are read-only, '
                     'the backend image drops every capability, '
                     'only the worker holds the mail password, '
                     'the worker outlasts its wait for running jobs and checks its ready file, '
                     'and the backend waits for migrate\n')


if __name__ == '__main__':
    main()
