"""Fail when the compose files' copies of the same settings disagree.

CI's Compose job runs this. The test stack copies production's hardening, so
that E2E catches a service an image change breaks under it, and all three
stacks copy the Redis ACL; nothing else compares the copies. Each file is
read as `docker compose config` resolves it, anchors and merges applied.
"""
import json
import subprocess
import sys

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


def main():
    prod = config('--env-file', '.env.prod.example')
    test = config('--env-file', '.env.test', '-f', 'docker-compose.test.yml', '--profile', 'e2e')
    dev = config('--env-file', '.env.dev', '-f', 'docker-compose.dev.yml')
    found = list(problems(prod, test, dev))
    sys.stdout.write(''.join(f'{p}\n' for p in found))
    if found:
        sys.exit(f'{len(found)} compose setting(s) differ')
    sys.stdout.write(f'{len(prod)} services and the Redis ACL match\n')


if __name__ == '__main__':
    main()
