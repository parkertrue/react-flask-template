"""No rate-limit key reads the database.

Flask-Limiter takes any error raised while it checks a limit for a Redis
outage: it falls back to memory, sees Redis recover, checks again and fails
again. A key that read MySQL would keep a request spinning there for as long
as MySQL stays down, and finish it when MySQL returns. A key reads the
request, the token or current_user, which the user loader has already fetched
when @jwt_required sits above the limits.

Each key_func is followed through the module-level functions it calls in its
own module, so a helper that reads the database counts too.
"""
import ast
from pathlib import Path

import pytest

APP = Path(__file__).resolve().parents[2] / 'app'


def _db_reads(source, name='module'):
    """'<name>: <function>' for every key_func that reaches `db`"""
    tree = ast.parse(source)
    functions = {node.name: node for node in tree.body if isinstance(node, ast.FunctionDef)}

    def reads_db(node, seen):
        for child in ast.walk(node):
            if isinstance(child, ast.Name) and child.id == 'db':
                return True
            if (isinstance(child, ast.Call) and isinstance(child.func, ast.Name)
                    and child.func.id in functions and child.func.id not in seen):
                seen.add(child.func.id)
                if reads_db(functions[child.func.id], seen):
                    return True
        return False

    for node in ast.walk(tree):
        if not isinstance(node, ast.keyword) or node.arg != 'key_func':
            continue
        if isinstance(node.value, ast.Lambda):
            key, label = node.value, f'lambda at line {node.value.lineno}'
        elif isinstance(node.value, ast.Name) and node.value.id in functions:
            key, label = functions[node.value.id], node.value.id
        else:
            # A parameter passed on, as account_password_limit does: its
            # callers' key_func arguments are checked where they are written
            continue
        if reads_db(key, set()):
            yield f'{name}: {label}'


def test_no_rate_limit_key_reads_the_database():
    found = [read for path in sorted(APP.rglob('*.py'))
             for read in _db_reads(path.read_text(encoding='utf-8'), path.relative_to(APP).as_posix())]

    assert found == []


@pytest.mark.parametrize(('source', 'expected'), [
    ('limit(key_func=lambda: db.session.get(User, 1).email)\n',
     ['module: lambda at line 1']),
    ('def key():\n    return db.session.get(User, 1).email\n\n'
     'limit(key_func=key)\n',
     ['module: key']),
    ('def lookup():\n    return db.session.get(User, 1)\n\n'
     'def key():\n    return lookup().email\n\n'
     'limit(key_func=key)\n',
     ['module: key']),
    ('def key():\n    return current_user.email\n\n'
     'limit(key_func=key)\n'
     'def unrelated():\n    return db.session.get(User, 1)\n',
     []),
])
def test_the_rule_finds_a_planted_read(source, expected):
    assert list(_db_reads(source)) == expected
