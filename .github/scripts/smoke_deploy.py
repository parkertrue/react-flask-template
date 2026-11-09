"""Deploy, fail and roll back with deploy.sh.

CI's Deploy smoke job runs this. It copies the working tree into a fresh
clone of a throwaway origin and commits a few versions to its main (a good
one, a second good one, one whose nginx stops at start, one whose worker
stops at start, one whose migration fails, one that does not build, one
whose db does not start, one that changes db, one built on a base image no
registry has, one that changes redis). Then it runs deploy.sh through each
case, after a stopped worker and deploys cut off
before and after the backend was replaced, against the locks of a live and
a dead deploy, then --latest as a timer would, through commits pushed
meanwhile, and checks what it left running, the images it kept, the
checkout and .env.deploy. Every failed check is printed, then it exits 1.
Needs Docker, git, bash, curl, ps, and a certificate pair in nginx/certs/;
ports 80 and 443 must be free.
"""
import os
import secrets
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
# Its own project and subnet, so it can run beside a local stack
PROJECT = 'deploy_smoke'
EDGE_SUBNET_PREFIX = '10.217.8'
# A base image only this host has, which a build that pulls cannot find
STALE_BASE = f'{PROJECT}-stale-base:1'

failures = []


def check(name, ok, detail=''):
    print(f"{'ok  ' if ok else 'FAIL'} {name}{f': {detail}' if not ok else ''}")
    if not ok:
        failures.append(name)


def run(*args, cwd=None, check=True, input=None, env=None):
    # UTF-8 whatever the locale: Windows' default can't decode the build's output
    return subprocess.run(args, cwd=cwd, check=check, capture_output=True, encoding='utf-8',
                          errors='replace', input=input, env=env and {**os.environ, **env})


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

    def compose(self, *args, check=True, env=None):
        return run('docker', 'compose', '--env-file', '.env.prod', *args, cwd=self.path, check=check,
                   env=env)


def env_file():
    """.env.prod.example with every placeholder filled in"""
    values = {
        'DB_USER': 'app',
        'DB_MIGRATION_USER': 'app_migrate',
        # Quoted, as Compose allows: the health check must read it as Compose does
        'SERVER_NAME': '"localhost www.localhost"',
        # The worker only checks them at start: nothing sends email here
        'EMAIL_URL': 'smtps://smoke:smokepass@smtp.invalid',
        'EMAIL_FROM': '"Smoke <no-reply@smoke.invalid>"',
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
    lines += [f'COMPOSE_PROJECT_NAME={PROJECT}', f'EDGE_SUBNET_PREFIX={EDGE_SUBNET_PREFIX}']
    return '\n'.join(lines) + '\n'


def running(service):
    """(image, container id) of the stack's container for service"""
    name = f'{PROJECT}-{service}-1'
    out = run('docker', 'inspect', '-f', '{{.Config.Image}} {{.Id}}', name, check=False).stdout.split()
    return tuple(out) if len(out) == 2 else (None, None)


def db():
    """The bundled db's settings (as Compose hashes them), command and health"""
    return run('docker', 'inspect', '-f', '{{index .Config.Labels "com.docker.compose.config-hash"}} '
               '{{json .Config.Cmd}} {{.State.Health.Status}}',
               f'{PROJECT}-db-1', check=False).stdout.strip()


def bash_pid(*, live):
    """A bash process's PID, as deploy.sh's $$ would be: a live one, to end
    with its stdin, or one that has exited"""
    process = subprocess.Popen([shutil.which('bash'), '-c', 'echo $$; read' if live else 'echo $$'],
                               stdin=subprocess.PIPE, stdout=subprocess.PIPE, encoding='utf-8')
    pid = process.stdout.readline().strip()
    if not live:
        process.wait()
    return process, pid


def worker_up():
    """Whether the worker's container is running"""
    return run('docker', 'inspect', '-f', '{{.State.Running}}', f'{PROJECT}-worker-1',
               check=False).stdout.strip() == 'true'


def serving(clone, sha):
    """Whether sha's images run, the worker included, and answer through nginx"""
    images = (running('backend')[0], running('worker')[0], running('nginx')[0])
    want = (f'{PROJECT}-backend:{sha}', f'{PROJECT}-backend:{sha}', f'{PROJECT}-nginx:{sha}')
    health = run('curl', '-fsS', '-k', '--max-time', '5', '--resolve', 'localhost:443:127.0.0.1',
                 'https://localhost/api/health', check=False)
    ok = (images == want and worker_up() and health.returncode == 0
          and clone.git('rev-parse', 'HEAD') == sha)
    return ok, (f'{images}, worker up {worker_up()}, health {health.returncode}, '
                f'HEAD {clone.git("rev-parse", "HEAD")}')


def kept():
    """The commits whose images are left, per image"""
    return {name: set(run('docker', 'image', 'ls', '--format', '{{.Tag}}', f'{PROJECT}-{name}')
                      .stdout.split()) for name in ('backend', 'nginx')}


def scenario(clone):
    good = clone.commit('A: the template')
    clone.write('README.md', clone.read('README.md') + '\nA second version.\n')
    second = clone.commit('B: a second good version')
    # server-mode.sh stops the container on an unknown mode
    clone.edit('nginx/Dockerfile', 'ENV NGINX_MODE=tls', 'ENV NGINX_MODE=broken')
    broken_nginx = clone.commit('C: nginx stops at start')
    clone.edit('nginx/Dockerfile', 'ENV NGINX_MODE=broken', 'ENV NGINX_MODE=tls')
    worker_command = 'command: ["python", "worker.py"]'
    clone.edit('docker-compose.yml', worker_command, 'command: ["python", "-c", "raise SystemExit(1)"]')
    broken_worker = clone.commit('J: the worker stops at start')
    clone.edit('docker-compose.yml', 'command: ["python", "-c", "raise SystemExit(1)"]', worker_command)
    migrations = clone.read('backend/migrations/env.py')
    clone.write('backend/migrations/env.py', "raise SystemExit('broken on purpose')\n" + migrations)
    broken_migration = clone.commit('D: the migration fails')
    clone.write('backend/migrations/env.py', migrations)
    dockerfile = clone.read('nginx/Dockerfile')
    clone.write('nginx/Dockerfile', dockerfile + 'RUN exit 1\n')
    unbuildable = clone.commit('E: the build fails')
    clone.write('nginx/Dockerfile', dockerfile)
    db_command = 'command: ["--innodb-buffer-pool-size=512M", "--disable-log-bin"]'
    clone.edit('docker-compose.yml', db_command, db_command[:-1] + ', "--no-such-option"]')
    broken_db = clone.commit('G: db does not start')
    clone.edit('docker-compose.yml', db_command[:-1] + ', "--no-such-option"]', db_command)
    clone.edit('docker-compose.yml', db_command, f'{db_command}\n    labels: [smoke.changed=1]')
    changed_db = clone.commit("L: db's settings change")
    clone.edit('docker-compose.yml', f'{db_command}\n    labels: [smoke.changed=1]', db_command)
    clone.edit('nginx/Dockerfile', 'FROM nginx:1.31-alpine', f'FROM {STALE_BASE}')
    stale_base = clone.commit('H: built on a base image no registry has')
    clone.write('nginx/Dockerfile', dockerfile)
    redis_image = 'image: redis:8.10-alpine'
    clone.edit('docker-compose.yml', redis_image, f'{redis_image}\n    labels: [smoke.changed=1]')
    changed_redis = clone.commit("I: redis's settings change")
    unpushed = clone.commit('F: never pushed', push=False)
    clone.git('checkout', '--quiet', '--detach', good)

    result = clone.deploy(good)
    check('the first deploy builds A', f'building {good}' in result.stdout, result.stdout)
    check('the first deploy serves A', *serving(clone, good))
    check('.env.deploy records A', clone.state().get('IMAGE_TAG') == good, clone.state())

    result = clone.deploy(good)
    check('deploying the deployed commit changes nothing',
          result.returncode == 0 and 'already deployed' in result.stdout, result.stdout)

    run('docker', 'stop', f'{PROJECT}-worker-1')
    result = clone.deploy(good)
    check('deploying the deployed commit brings back a stopped worker',
          'already deployed' not in result.stdout and serving(clone, good)[0],
          f'{result.stdout} {serving(clone, good)[1]}')

    result = clone.deploy(second)
    check('the second deploy serves B', *serving(clone, second))
    # The deploy creates migrate's container afresh; each start of it logs this
    log = run('docker', 'logs', f'{PROJECT}-migrate-1', check=False)
    starts = (log.stdout + log.stderr).count('Database and Redis are up')
    check('migrate runs once per deploy', starts == 1, f'{starts} starts')
    check('.env.deploy records B, then A', (clone.state().get('IMAGE_TAG'),
          clone.state().get('PREVIOUS_IMAGE_TAG')) == (second, good), clone.state())

    result = clone.deploy(broken_nginx)
    check('a deploy that does not come up fails', result.returncode == 1, result.stderr)
    check("the rollback reuses B's images", f'using the images already built for {second}'
          in result.stdout, result.stdout)
    check('it is rolled back to B', *serving(clone, second))
    check('.env.deploy records C as failed', (clone.state().get('IMAGE_TAG'),
          clone.state().get('FAILED_IMAGE_TAG')) == (second, broken_nginx), clone.state())

    result = clone.deploy(broken_worker)
    check('a deploy whose worker does not start fails', result.returncode == 1, result.stderr)
    check('it is rolled back to B, the worker included', *serving(clone, second))
    check('.env.deploy records J as failed', (clone.state().get('IMAGE_TAG'),
          clone.state().get('FAILED_IMAGE_TAG')) == (second, broken_worker), clone.state())

    backend = running('backend')
    # Each failure below starts from another checkout than the deployed
    # one, as a deploy cut off halfway leaves it, and must end on B's
    clone.git('checkout', '--quiet', '--detach', good)
    result = clone.deploy(broken_migration)
    check('a failed migration fails the deploy', result.returncode == 1, result.stderr)
    check('the running backend was never replaced', running('backend') == backend, running('backend'))
    check('B still serves, checked out', *serving(clone, second))
    check('.env.deploy records D as failed', (clone.state().get('IMAGE_TAG'),
          clone.state().get('FAILED_IMAGE_TAG')) == (second, broken_migration), clone.state())

    before = clone.state()
    clone.git('checkout', '--quiet', '--detach', good)
    result = clone.deploy(unbuildable)
    check('a commit that does not build is refused', result.returncode == 1
          and 'nothing changed' in result.stderr, result.stderr)
    check('nothing changed for it, nor is it recorded as failed, and B is checked out',
          clone.state() == before and serving(clone, second)[0],
          f'{clone.state()} {serving(clone, second)[1]}')

    # What a deploy of A killed halfway leaves, once the operator has removed
    # its lock: A's backend running, A checked out, and .env.deploy still
    # naming B. The operator then deploys B, the commit it records.
    clone.compose('up', '-d', '--no-build', '--no-deps', '--wait', 'backend', env={'IMAGE_TAG': good})
    clone.git('checkout', '--quiet', '--detach', good)
    result = clone.deploy(second)
    check('after a deploy cut off halfway, the recorded commit deploys again',
          'already deployed' not in result.stdout and serving(clone, second)[0],
          f'{result.stdout} {serving(clone, second)[1]}')
    check('.env.deploy still records B, then A', (clone.state().get('IMAGE_TAG'),
          clone.state().get('PREVIOUS_IMAGE_TAG')) == (second, good), clone.state())

    healthy_db = db()
    result = clone.deploy(broken_db)
    check('a db that does not start fails the deploy', result.returncode == 1
          and 'did not come up' in result.stderr, result.stderr)
    check("db is back on B's settings, healthy", db() == healthy_db, db())
    check('B still serves after the db failed', *serving(clone, second))
    check('.env.deploy records G as failed', (clone.state().get('IMAGE_TAG'),
          clone.state().get('FAILED_IMAGE_TAG')) == (second, broken_db), clone.state())

    # What a deploy of L killed before it replaced the backend leaves: B's
    # backend running, L checked out, and db on L's settings. Deploying B,
    # the commit .env.deploy records, must put both back.
    clone.git('checkout', '--quiet', '--detach', changed_db)
    clone.compose('up', '-d', '--no-build', '--wait', 'db', 'redis')
    check("the cut-off deploy moved db to L's settings", db() != healthy_db, db())
    result = clone.deploy(second)
    check('after a deploy cut off before the backend, the recorded commit deploys again',
          'already deployed' not in result.stdout and serving(clone, second)[0],
          f'{result.stdout} {serving(clone, second)[1]}')
    check("db is back on B's settings after the cut-off deploy", db() == healthy_db, db())

    # Pulled first: a build's base images need not be in the image list
    run('docker', 'pull', '--quiet', 'nginx:1.31-alpine')
    run('docker', 'tag', 'nginx:1.31-alpine', STALE_BASE)
    before = clone.state()
    result = clone.deploy(stale_base)
    check('the build pulls its base images', result.returncode == 1
          and 'could not build' in result.stderr, result.stderr)
    check('nothing changed for the stale base', clone.state() == before
          and serving(clone, second)[0], clone.state())

    result = clone.deploy('main')
    check('a local branch name is refused', result.returncode == 1
          and 'is a local branch' in result.stderr, result.stderr)

    result = clone.deploy(unpushed)
    check('a commit not on origin/main is refused', result.returncode == 1
          and 'is not on origin/main' in result.stderr, result.stderr)

    clone.write('README.md', clone.read('README.md') + 'An edit on the server.\n')
    result = clone.deploy(good)
    check('a clone with uncommitted changes is refused', result.returncode == 1
          and 'uncommitted changes' in result.stderr, result.stderr)
    clone.git('checkout', '--', 'README.md')

    lock = clone.path / '.deploy.lock'
    # A lock with no PID yet, as a deploy that is starting holds it
    lock.mkdir()
    result = clone.deploy(good)
    check('a deploy is refused while one is starting', result.returncode == 1
          and 'another deploy is running' in result.stderr, result.stderr)
    lock.rmdir()

    holder, pid = bash_pid(live=True)
    lock.mkdir()
    (lock / 'pid').write_text(f'{pid}\n', encoding='utf-8')
    result = clone.deploy(good)
    check('a second deploy at once is refused', result.returncode == 1
          and f'another deploy is running (pid {pid})' in result.stderr, result.stderr)
    check("the live deploy's lock is left alone", (lock / 'pid').exists(), lock)
    holder.communicate('\n')
    shutil.rmtree(lock, ignore_errors=True)

    _, pid = bash_pid(live=False)
    lock.mkdir()
    (lock / 'pid').write_text(f'{pid}\n', encoding='utf-8')
    result = clone.deploy(second)
    check("a killed deploy's lock is taken over", result.returncode == 0
          and f'taking over the lock of deploy {pid}' in result.stdout
          and 'already deployed' in result.stdout, result.stdout + result.stderr)
    check('the taken-over lock is removed afterwards', not lock.exists(), lock)
    # So a failure here does not refuse every deploy after it
    shutil.rmtree(lock, ignore_errors=True)

    result = clone.deploy('--rollback')
    check('--rollback builds nothing', f'using the images already built for {good}'
          in result.stdout and 'building' not in result.stdout, result.stdout)
    check('--rollback serves A again', *serving(clone, good))
    check('.env.deploy records A, then B', (clone.state().get('IMAGE_TAG'),
          clone.state().get('PREVIOUS_IMAGE_TAG')) == (good, second), clone.state())
    check("only the deployed and previous commits' images are kept",
          kept() == {'backend': {good, second}, 'nginx': {good, second}}, kept())

    # Redis external: its profile off, the bundled one's container (still
    # answering as redis) stands in for it, and a deploy must leave it alone
    env = clone.read('.env.prod')
    (clone.path / '.env.prod').write_text(env.replace(
        'COMPOSE_PROFILES=bundled-db,bundled-redis', 'COMPOSE_PROFILES=bundled-db'), newline='\n')
    redis = running('redis')
    result = clone.deploy(changed_redis)
    check('a deploy with redis external serves I', *serving(clone, changed_redis))
    check('it leaves redis alone, though its settings changed', running('redis') == redis,
          running('redis'))
    (clone.path / '.env.prod').write_text(env, newline='\n')

    # --latest, as a timer runs it: I is origin/main's newest commit
    backend = running('backend')
    result = clone.deploy('--latest')
    check('--latest on the deployed commit changes nothing', result.returncode == 0
          and 'already deployed' in result.stdout and running('backend') == backend, result.stdout)

    clone.write('README.md', clone.read('README.md') + 'A version the timer finds.\n')
    newest = clone.commit('J: pushed after the last deploy')
    result = clone.deploy('--latest')
    check('--latest deploys a newer commit', *serving(clone, newest))

    result = clone.deploy('--rollback')
    check('--rollback records the commit it leaves as failed', (clone.state().get('IMAGE_TAG'),
          clone.state().get('FAILED_IMAGE_TAG')) == (changed_redis, newest), clone.state())

    backend = running('backend')
    result = clone.deploy('--latest')
    check('--latest leaves the failed commit alone', result.returncode == 0
          and 'failed last' in result.stdout and running('backend') == backend, result.stdout)

    # On main's newest, J, not the I the rollback checked out
    clone.git('checkout', '--quiet', '--detach', newest)
    clone.write('README.md', clone.read('README.md') + 'A fix.\n')
    fixed = clone.commit('K: pushed after the failed one')
    result = clone.deploy('--latest')
    check('--latest deploys the commit after a failed one', *serving(clone, fixed))

    result = clone.deploy(newest)
    check('deploying a failed commit by name clears it', serving(clone, newest)[0]
          and clone.state().get('FAILED_IMAGE_TAG') == '', clone.state())


def main():
    base = Path(tempfile.mkdtemp(prefix='deploy-smoke-'))
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
        images = [image for name in ('backend', 'nginx') for image in run(
            'docker', 'image', 'ls', '--format', '{{.Repository}}:{{.Tag}}', f'{PROJECT}-{name}',
            check=False).stdout.split()]
        if images:
            run('docker', 'image', 'rm', '-f', *images, check=False)
        run('docker', 'image', 'rm', STALE_BASE, check=False)
        shutil.rmtree(base, ignore_errors=True)
    print(f'{time.monotonic() - started:.0f} s')
    if failures:
        sys.exit(f'{len(failures)} check(s) failed')


if __name__ == '__main__':
    main()
