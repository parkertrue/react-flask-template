"""Deploy, fail and roll back with deploy.sh, against a registry of its own.

CI's Deploy smoke job runs this. It copies the working tree into a fresh
clone of a throwaway origin, commits a few versions to its main (a good one,
a second good one, one whose nginx stops at start, one whose migration
fails), builds each commit's images and pushes them to a registry on
localhost, as CI's Publish job does to GHCR. Then it runs deploy.sh through
each case and checks what it left running, the checkout and .env.deploy.
Every failed check is printed, then it exits 1. Needs Docker, git, bash,
curl, and a certificate pair in nginx/certs/; ports 80 and 443 must be free.
"""
import secrets
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
REGISTRY_PORT = 5057
REGISTRY_IMAGE = ('registry:3.0.0@sha256:'
                  '6c5666b861f3505b116bb9aa9b25175e71210414bd010d92035ff64018f9457e')
REGISTRY_NAME = 'deploy-smoke-registry'
IMAGE_REPOSITORY = f'localhost:{REGISTRY_PORT}/app'
# Its own subnet, so it can run beside a local test stack
EDGE_SUBNET_PREFIX = '10.217.8'

failures = []


def check(name, ok, detail=''):
    print(f"{'ok  ' if ok else 'FAIL'} {name}{f': {detail}' if not ok else ''}")
    if not ok:
        failures.append(name)


def run(*args, cwd=None, check=True, input=None):
    return subprocess.run(args, cwd=cwd, check=check, capture_output=True, text=True, input=input)


class Clone:
    """A fresh clone of a throwaway origin, holding the working tree's files"""

    def __init__(self, base):
        self.origin = base / 'origin.git'
        self.path = base / 'app'
        run('git', 'init', '--quiet', '--bare', '--initial-branch=main', str(self.origin))
        run('git', 'init', '--quiet', '--initial-branch=main', str(self.path))
        self.git('config', 'user.name', 'Deploy smoke')
        self.git('config', 'user.email', 'deploy-smoke@example.com')
        self.git('remote', 'add', 'origin', str(self.origin))
        # The working tree as it is, so a local run tests uncommitted changes
        files = run('git', 'ls-files', '-z', '--cached', '--others', '--exclude-standard',
                    cwd=ROOT).stdout.split('\0')
        for name in filter(None, files):
            source = ROOT / name
            if source.is_file():
                (self.path / name).parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(source, self.path / name)
        shutil.copytree(ROOT / 'nginx' / 'certs', self.path / 'nginx' / 'certs')
        (self.path / '.env.prod').write_text(env_file(), encoding='utf-8', newline='\n')

    def git(self, *args):
        return run('git', *args, cwd=self.path).stdout.strip()

    def commit(self, message, push=True):
        self.git('add', '--all')
        self.git('commit', '--quiet', '--allow-empty', '-m', message)
        if push:
            self.git('push', '--quiet', 'origin', 'HEAD:main')
        return self.git('rev-parse', 'HEAD')

    def read(self, name):
        return (self.path / name).read_text(encoding='utf-8')

    def write(self, name, text):
        (self.path / name).write_text(text, encoding='utf-8')

    def edit(self, name, old, new):
        text = self.read(name)
        assert text.count(old) == 1, f'{name}: {old!r}'
        self.write(name, text.replace(old, new))

    def publish(self, sha):
        """Build sha's images and push them, as the Publish job does"""
        self.git('checkout', '--quiet', '--detach', sha)
        for name, args in (('backend', ['backend']), ('nginx', ['-f', 'nginx/Dockerfile', '.'])):
            image = f'{IMAGE_REPOSITORY}/{name}:{sha}'
            run('docker', 'build', '--quiet', '-t', image, *args, cwd=self.path)
            run('docker', 'push', '--quiet', image)
        self.git('checkout', '--quiet', 'main')

    def deploy(self, *args):
        # By PATH: Windows would run System32's bash (WSL) for a bare name
        result = run(shutil.which('bash'), 'deploy.sh', *args, cwd=self.path, check=False)
        print(f'$ ./deploy.sh {" ".join(args)} -> exit {result.returncode}')
        print(''.join(f'  {line}\n' for line in (result.stdout + result.stderr).splitlines()))
        return result

    def state(self):
        path = self.path / '.env.deploy'
        lines = path.read_text(encoding='utf-8').splitlines() if path.exists() else []
        return dict(line.split('=', 1) for line in lines)

    def compose(self, *args, check=True):
        return run('docker', 'compose', '--env-file', '.env.prod', *args, cwd=self.path, check=check)


def env_file():
    """.env.prod.example with every placeholder filled in"""
    values = {
        'DB_USER': 'app',
        'DB_MIGRATION_USER': 'app_migrate',
        'SERVER_NAME': 'localhost',
    }
    lines = []
    for line in (ROOT / '.env.prod.example').read_text(encoding='utf-8').splitlines():
        key, _, value = line.partition('=')
        if line.startswith('#') or not value:
            continue
        if key in values:
            value = values[key]
        elif value.startswith('your_'):
            value = secrets.token_hex(32)
        lines.append(f'{key}={value}')
    lines += [f'IMAGE_REPOSITORY={IMAGE_REPOSITORY}', f'EDGE_SUBNET_PREFIX={EDGE_SUBNET_PREFIX}']
    return '\n'.join(lines) + '\n'


def running(service):
    """(image, container id) of the stack's container for service"""
    name = f'app-{service}-1'
    out = run('docker', 'inspect', '-f', '{{.Config.Image}} {{.Id}}', name, check=False).stdout.split()
    return tuple(out) if len(out) == 2 else (None, None)


def serving(clone, sha):
    """Whether sha's images run and answer through nginx"""
    images = (running('backend')[0], running('nginx')[0])
    want = (f'{IMAGE_REPOSITORY}/backend:{sha}', f'{IMAGE_REPOSITORY}/nginx:{sha}')
    health = run('curl', '-fsS', '-k', '--max-time', '5', '--resolve', 'localhost:443:127.0.0.1',
                 'https://localhost/api/health', check=False)
    ok = images == want and health.returncode == 0 and clone.git('rev-parse', 'HEAD') == sha
    return ok, f'{images}, health {health.returncode}, HEAD {clone.git("rev-parse", "HEAD")}'


def scenario(clone):
    good = clone.commit('A: the template')
    clone.write('README.md', clone.read('README.md') + '\nA second version.\n')
    second = clone.commit('B: a second good version')
    # server-mode.sh stops the container on an unknown mode
    clone.edit('nginx/Dockerfile', 'ENV NGINX_MODE=tls', 'ENV NGINX_MODE=broken')
    broken_nginx = clone.commit('C: nginx stops at start')
    clone.edit('nginx/Dockerfile', 'ENV NGINX_MODE=broken', 'ENV NGINX_MODE=tls')
    migrations = clone.read('backend/migrations/env.py')
    clone.write('backend/migrations/env.py', "raise SystemExit('broken on purpose')\n" + migrations)
    broken_migration = clone.commit('D: the migration fails')
    clone.write('backend/migrations/env.py', migrations)
    unpublished = clone.commit('E: no images yet')
    unpushed = clone.commit('F: never pushed', push=False)
    clone.git('checkout', '--quiet', '--detach', good)
    for sha in (good, second, broken_nginx, broken_migration):
        print(f'publishing {sha[:12]}')
        clone.publish(sha)
    clone.git('checkout', '--quiet', '--detach', good)

    clone.deploy(good)
    check('the first deploy serves A', *serving(clone, good))
    check('.env.deploy records A', clone.state().get('IMAGE_TAG') == good, clone.state())

    result = clone.deploy(good)
    check('deploying the deployed commit changes nothing',
          result.returncode == 0 and 'already deployed' in result.stdout, result.stdout)

    clone.deploy(second)
    check('the second deploy serves B', *serving(clone, second))
    check('.env.deploy records B, then A', (clone.state().get('IMAGE_TAG'),
          clone.state().get('PREVIOUS_IMAGE_TAG')) == (second, good), clone.state())

    result = clone.deploy(broken_nginx)
    check('a deploy that does not come up fails', result.returncode == 1, result.stderr)
    check('it is rolled back to B', *serving(clone, second))
    check('.env.deploy records C as failed', (clone.state().get('IMAGE_TAG'),
          clone.state().get('FAILED_IMAGE_TAG')) == (second, broken_nginx), clone.state())

    backend = running('backend')
    result = clone.deploy(broken_migration)
    check('a failed migration fails the deploy', result.returncode == 1, result.stderr)
    check('the running backend was never replaced', running('backend') == backend, running('backend'))
    check('B still serves', *serving(clone, second))
    check('.env.deploy records D as failed', (clone.state().get('IMAGE_TAG'),
          clone.state().get('FAILED_IMAGE_TAG')) == (second, broken_migration), clone.state())

    before = clone.state()
    result = clone.deploy(unpublished)
    check('a commit without images is refused', result.returncode == 1
          and 'nothing changed' in result.stderr, result.stderr)
    check('nothing changed for it', clone.state() == before and serving(clone, second)[0],
          clone.state())

    result = clone.deploy(unpushed)
    check('a commit not on origin/main is refused', result.returncode == 1
          and 'is not on origin/main' in result.stderr, result.stderr)

    clone.write('README.md', clone.read('README.md') + 'An edit on the server.\n')
    result = clone.deploy(good)
    check('a clone with uncommitted changes is refused', result.returncode == 1
          and 'uncommitted changes' in result.stderr, result.stderr)
    clone.git('checkout', '--', 'README.md')

    (clone.path / '.deploy.lock').mkdir()
    result = clone.deploy(good)
    check('a second deploy at once is refused', result.returncode == 1
          and 'another deploy is running' in result.stderr, result.stderr)
    (clone.path / '.deploy.lock').rmdir()

    clone.deploy('--rollback')
    check('--rollback serves A again', *serving(clone, good))
    check('.env.deploy records A, then B', (clone.state().get('IMAGE_TAG'),
          clone.state().get('PREVIOUS_IMAGE_TAG')) == (good, second), clone.state())


def main():
    base = Path(tempfile.mkdtemp(prefix='deploy-smoke-'))
    run('docker', 'run', '-d', '--name', REGISTRY_NAME, '-p', f'127.0.0.1:{REGISTRY_PORT}:5000',
        REGISTRY_IMAGE)
    clone = None
    started = time.monotonic()
    try:
        clone = Clone(base)
        scenario(clone)
    finally:
        if failures and clone:
            print(clone.compose('logs', '--no-color', '--tail', '50', check=False).stdout)
        if clone:
            clone.compose('down', '-v', check=False)
        images = run('docker', 'images', '-q', f'{IMAGE_REPOSITORY}/*', check=False).stdout.split()
        if images:
            run('docker', 'image', 'rm', '-f', *set(images), check=False)
        run('docker', 'rm', '-f', '-v', REGISTRY_NAME, check=False)
        shutil.rmtree(base, ignore_errors=True)
    print(f'{time.monotonic() - started:.0f} s')
    if failures:
        sys.exit(f'{len(failures)} check(s) failed')


if __name__ == '__main__':
    main()
