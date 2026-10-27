"""Fail when db/init/01-app-user.sh stops refusing what it must refuse, or
hands MySQL other SQL than it should.

CI's Compose job runs this. The script runs once, when the bundled MySQL's
volume is created, so a broken refusal would surface only on a real
deployment: it is the one guard on the root password's placeholder, which
the app never sees. Each case runs the script with `sh` and a stub `mysql`
first on PATH that saves what it was given; no database is needed.
"""
import os
import subprocess
import sys
import tempfile
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[2] / 'db' / 'init' / '01-app-user.sh'

# Saves its arguments, the password it was given and the SQL on its stdin
STUB = '''#!/bin/sh
printf '%s' "$*" > "$STUB_OUT/args"
printf '%s' "$MYSQL_PWD" > "$STUB_OUT/password"
cat > "$STUB_OUT/sql"
'''

# What the MySQL image hands the script, with a quote and a backslash where
# literal() must escape them
VALID = {
    'MYSQL_DATABASE': 'app_db',
    'MYSQL_USER': 'app_migrate',
    'MYSQL_ROOT_PASSWORD': 'rootpass',
    'MYSQL_PASSWORD': 'migratepass',
    'DB_USER': "o'b",
    'DB_PASSWORD': "it's\\x",
}

EXPECTED_SQL = (
    "CREATE USER 'o''b'@'%' IDENTIFIED BY 'it''s\\\\x';\n"
    "GRANT SELECT, INSERT, UPDATE, DELETE ON `app\\_db`.* TO 'o''b'@'%';\n"
)

PLACEHOLDER = 'a password is still the .env.prod.example placeholder'
SAME_USER = 'DB_USER and DB_MIGRATION_USER must be different users'
DATABASE_NAME = 'unexpected database name'

# (what the case changes, the message the script must refuse it with)
REFUSALS = [
    ({'DB_PASSWORD': 'your_db_password_here'}, PLACEHOLDER),
    ({'MYSQL_PASSWORD': 'your_migration_password_here'}, PLACEHOLDER),
    ({'MYSQL_ROOT_PASSWORD': 'your_root_password_here'}, PLACEHOLDER),
    ({'DB_USER': 'app_migrate'}, SAME_USER),
    ({'MYSQL_DATABASE': ''}, DATABASE_NAME),
    ({'MYSQL_DATABASE': 'app-db'}, DATABASE_NAME),
    ({'MYSQL_DATABASE': 'app`db'}, DATABASE_NAME),
]


def run(stub_dir, out, changes):
    for saved in out.iterdir():
        saved.unlink()
    env = {
        **VALID, **changes,
        'PATH': f'{stub_dir}{os.pathsep}{os.environ["PATH"]}',
        'STUB_OUT': str(out),
    }
    return subprocess.run(['sh', str(SCRIPT)], env=env, capture_output=True, text=True)


def problems(stub_dir, out):
    result = run(stub_dir, out, {})
    if result.returncode != 0:
        yield f'valid values: exit {result.returncode}: {result.stderr.strip()}'
    else:
        if (out / 'sql').read_text() != EXPECTED_SQL:
            yield f'valid values: mysql was handed {(out / "sql").read_text()!r}'
        if (out / 'args').read_text() != '--protocol=socket -uroot':
            yield f'valid values: mysql was run with {(out / "args").read_text()!r}'
        if (out / 'password').read_text() != VALID['MYSQL_ROOT_PASSWORD']:
            yield 'valid values: mysql was not given the root password'
    for changes, message in REFUSALS:
        result = run(stub_dir, out, changes)
        if result.returncode == 0 or message not in result.stderr:
            yield f'{changes}: not refused with "{message}" (exit {result.returncode})'
        if (out / 'sql').exists():
            yield f'{changes}: mysql ran anyway'


def main():
    with tempfile.TemporaryDirectory() as tmp:
        stub_dir, out = Path(tmp, 'bin'), Path(tmp, 'out')
        stub_dir.mkdir()
        out.mkdir()
        stub = stub_dir / 'mysql'
        stub.write_text(STUB, newline='\n')
        stub.chmod(0o755)
        found = list(problems(stub_dir, out))
    sys.stdout.write(''.join(f'{p}\n' for p in found))
    if found:
        sys.exit(f'{len(found)} init script check(s) failed')
    sys.stdout.write(f'The init script creates the app user and refuses all {len(REFUSALS)} bad values\n')


if __name__ == '__main__':
    main()
