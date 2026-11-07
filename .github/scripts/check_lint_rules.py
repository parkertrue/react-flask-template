"""Fail when a ruff rule or a mypy check the backend relies on stops firing.

CI's Backend unit job runs this, after Lint and Type check. The rules are
config, and config fails silently: a code dropped from `select`, a misspelled
path in `banned-api` or strict mode turned off reports nothing. So this
plants one violation per rule, runs it through ruff with backend/ruff.toml or
mypy with backend/mypy.ini, and expects that rule's code, as
frontend/src/__tests__/eslintRules.test.ts does for ESLint. It runs here,
not in pytest, because ruff bans `subprocess` in backend/.
"""
import json
import subprocess
import sys
import tempfile
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[2] / 'backend'
TEST = 'tests/unit/test_probe.py'
APP = 'app/probe.py'

# (file it pretends to be, code, the rule that must fire)
PLANTED = (
    # Rules CLAUDE.md states, through banned-api
    (TEST, 'import pytest\n\npytest.skip()\n', 'TID251'),
    (TEST, 'import pytest\n\n\n@pytest.mark.skip\ndef test_x():\n    pass\n', 'TID251'),
    (TEST, "import pytest\n\n\n@pytest.mark.skipif(True, reason='x')\ndef test_x():\n    pass\n",
     'TID251'),
    (TEST, "import pytest\n\npytest.importorskip('x')\n", 'TID251'),
    (TEST, 'import pytest\n\n\n@pytest.mark.xfail\ndef test_x():\n    pass\n', 'TID251'),
    (APP, 'from flask_jwt_extended import get_jwt_identity\n\nget_jwt_identity()\n', 'TID251'),
    (APP, 'import subprocess\n\nsubprocess.run([])\n', 'TID251'),
    (APP, "import os\n\nos.system('x')\n", 'TID251'),
    # Relative imports, which tests/unit/test_import_rules.py cannot see
    (APP, 'from . import probe\n\nprobe()\n', 'TID252'),
    # Leftovers
    (APP, "print('x')\n", 'T201'),
    (APP, '# x = 1\n', 'ERA001'),
    (APP, '# TODO: x\n', 'FIX002'),
    (APP, '# FIXME: x\n', 'FIX001'),
    # Naive datetimes, code from strings, hedged tests
    (APP, 'from datetime import datetime\n\ndatetime.now()\n', 'DTZ005'),
    (APP, "exec('x')\n", 'S102'),
    (APP, "eval('x')\n", 'S307'),
    (APP, "def query(x):\n    return f'SELECT * FROM users WHERE id = {x}'\n", 'S608'),
    (TEST, 'import pytest\n\n\ndef test_x():\n    with pytest.raises(Exception):\n        pass\n',
     'B017'),
    # Bugs, style and noqa
    (APP, 'import os\n', 'F401'),
    (APP, 'x = None\nprint(x == None)  # noqa: T201\n', 'E711'),
    (APP, 'x = "a"\n', 'Q000'),
    (APP, 'x = 1  # noqa: E501\n', 'RUF100'),
)


def codes(filename, code):
    result = subprocess.run(
        ['ruff', 'check', '--config', str(BACKEND / 'ruff.toml'), '--output-format', 'json',
         '--stdin-filename', filename, '-'],
        cwd=BACKEND, input=code, capture_output=True, text=True, check=False)
    return {message['code'] for message in json.loads(result.stdout)}


# (code, the mypy error code that must fire)
PLANTED_TYPES = (
    # Strict mode: every function annotated
    ('def f(x):\n    return x\n', 'no-untyped-def'),
    # A plain type error, so mypy is running at all
    ("x: int = 'a'\n", 'assignment'),
)


def type_codes(code):
    """mypy's error codes for this code, checked with backend/mypy.ini"""
    with tempfile.TemporaryDirectory() as directory:
        probe = Path(directory) / 'probe.py'
        probe.write_text(code)
        # A file named on the command line stands in for the config's `files`
        result = subprocess.run(
            ['mypy', '--config-file', 'mypy.ini', '--output', 'json', str(probe)],
            cwd=BACKEND, capture_output=True, text=True, check=False)
    return {json.loads(line)['code'] for line in result.stdout.splitlines() if line}


def main():
    failures = [f'{rule} did not fire for {filename}: {code!r}'
                for filename, code, rule in PLANTED if rule not in codes(filename, code)]
    failures += [f'mypy {rule} did not fire for {code!r}'
                 for code, rule in PLANTED_TYPES if rule not in type_codes(code)]
    # And a clean file stays clean, so the checks above cannot all pass on noise
    if clean := codes(APP, "x = 'a'\n"):
        failures.append(f'a clean file reports {sorted(clean)}')
    if clean := type_codes('x: int = 1\n'):
        failures.append(f'mypy reports {sorted(clean)} for a clean file')
    for failure in failures:
        print(failure)
    if failures:
        sys.exit(1)
    print(f'{len(PLANTED) + len(PLANTED_TYPES)} planted violations, each caught by its rule')


if __name__ == '__main__':
    main()
