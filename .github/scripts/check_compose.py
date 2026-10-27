"""Fail when the compose files' copies of the same settings disagree.

CI's Compose job runs this. The test stack copies production's hardening, so
that E2E catches a service an image change breaks under it, and all three
stacks copy the Redis ACL and mount the database's init scripts, which create
the app's data-only user; nothing else compares the copies. It also pins the
production backend's wait for `migrate` to succeed, which README's deploy
(migrate first, then `up -d`) relies on. Each file is read as
`docker compose config` resolves it, anchors and merges applied.
"""
import json
import subprocess
import sys
from pathlib import Path

# db/init, where every stack's db service must find its init scripts
INIT_SCRIPTS = Path(__file__).resolve().parents[2] / 'db' / 'init'

# The hardening each test service must share with its production namesake
HARDENING = ('security_opt', 'cap_drop', 'cap_add', 'read_only', 'pids')


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


def init_mounts(db):
    """What the db service mounts as the MySQL image's init scripts"""
    return [(Path(volume['source']), volume.get('read_only', False))
            for volume in db.get('volumes', [])
            if volume['target'] == '/docker-entrypoint-initdb.d']


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
            yield f'redis: the ACL in {stack} differs from production\'s'
    for stack, services in (('production', prod), ('test', test), ('dev', dev)):
        if init_mounts(services['db']) != [(INIT_SCRIPTS, True)]:
            yield f'db: {stack} does not mount db/init read-only as its init scripts'
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
                     'and the backend waits for migrate\n')


if __name__ == '__main__':
    main()
