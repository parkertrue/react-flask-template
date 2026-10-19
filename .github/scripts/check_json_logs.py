"""Fail when a line read from stdin is not a JSON object, printing each one.

CI's E2E job pipes the migrate and backend containers' logs through this: a
log shipper parses each line as JSON, so a plain-text line (gunicorn's own
format, a print) is one it would drop. The backend, gunicorn and the
migrations log through JsonFormatter (backend/app/utils/log.py,
backend/gunicorn_logging.json, backend/migrations/alembic.ini).
"""
import json
import sys


def is_json_object(line):
    try:
        return isinstance(json.loads(line), dict)
    except ValueError:
        return False


lines = [line.rstrip() for line in sys.stdin if line.strip()]
plain = [line for line in lines if not is_json_object(line)]
sys.stdout.write(''.join(f'Not JSON: {line}\n' for line in plain))
summary = f'{len(lines) - len(plain)} of {len(lines)} lines are JSON'
if plain or not lines:
    sys.exit(summary)
sys.stdout.write(summary + '\n')
