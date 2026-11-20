"""No test writes a value a new app renames: README's "Starting a New App"
has it change the sender in .env.dev and .env.test (step 5), and a test
holding the template's own would turn red then. A test reads it from the
config instead, as tests/integration/test_mail.py does."""
from email.utils import parseaddr
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[2]
TESTS = BACKEND / 'tests'


def _env_value(name):
    """A value of .env.test, quotes and all removed"""
    for line in (BACKEND.parent / '.env.test').read_text(encoding='utf-8').splitlines():
        key, _, value = line.partition('=')
        if key.strip() == name:
            return value.strip().strip('"\'')
    raise AssertionError(f'{name} is not in .env.test')


def test_no_test_writes_the_test_sender():
    sender = parseaddr(_env_value('EMAIL_FROM'))[1]

    writers = [path.relative_to(BACKEND).as_posix() for path in TESTS.rglob('*.py')
               if sender in path.read_text(encoding='utf-8')]

    assert sender.count('@') == 1
    assert writers == []
