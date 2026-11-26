"""requirements.in lists every package the backend's code imports directly.

A package that only arrives through another (SQLAlchemy through
Flask-SQLAlchemy) still works today, but the day that one drops or swaps it,
the import breaks with nothing in requirements.in to say it was needed.
"""
import ast
import re
import sys
from importlib.metadata import packages_distributions
from pathlib import Path

import pytest

BACKEND = Path(__file__).resolve().parents[2]
# The code the production image runs: the app, its migrations and the
# scripts beside them (tests and their tools are requirements-dev.in's)
SOURCES = ['app', 'migrations', '*.py']


def _name(requirement):
    """A distribution's name in one spelling: 'Flask_SQLAlchemy' ->
    'flask-sqlalchemy'"""
    return re.sub(r'[-_.]+', '-', requirement).lower()


def _listed(requirements_in):
    lines = (line.split('#')[0].strip() for line in requirements_in.read_text(encoding='utf-8').splitlines())
    return {_name(re.split(r'[\s\[<>=!~;]', line)[0]) for line in lines if line}


def _imported(root):
    """Every top-level module the code under root imports, standard library
    and app aside"""
    files = {file for pattern in SOURCES
             for found in root.glob(pattern)
             for file in ([found] if found.is_file() else found.rglob('*.py'))}
    for file in sorted(files):
        for node in ast.walk(ast.parse(file.read_text(encoding='utf-8'))):
            if isinstance(node, ast.Import):
                names = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom) and node.level == 0:
                names = [node.module]
            else:
                continue
            for name in names:
                top = name.split('.')[0]
                if top != 'app' and top not in sys.stdlib_module_names:
                    yield top


def _unlisted(root):
    listed = _listed(root / 'requirements.in')
    distributions = packages_distributions()
    return sorted({module for module in _imported(root)
                   if not listed & {_name(dist) for dist in distributions.get(module, [])}})


def test_every_imported_package_is_listed():
    assert _unlisted(BACKEND) == []


class TestTheCheckItself:
    @pytest.fixture
    def backend(self, tmp_path):
        (tmp_path / 'app').mkdir()
        (tmp_path / 'requirements.in').write_text(
            '# a comment\nFlask>=3  # with a pin\nflask_sqlalchemy[async]\n', encoding='utf-8')
        return tmp_path

    @pytest.mark.parametrize('source', [
        'import sqlalchemy',
        'from werkzeug.exceptions import HTTPException',
        'import redis.retry',
    ])
    def test_finds_a_package_listed_only_through_another(self, backend, source):
        (backend / 'app' / 'x.py').write_text(source, encoding='utf-8')

        assert _unlisted(backend) == [source.split()[1].split('.')[0]]

    @pytest.mark.parametrize(('path', 'source'), [
        ('migrations/versions/0001_x.py', 'import alembic'),
        ('wait_for_services.py', 'import pymysql'),
    ])
    def test_reads_the_scripts_beside_the_app(self, backend, path, source):
        (backend / path).parent.mkdir(parents=True, exist_ok=True)
        (backend / path).write_text(source, encoding='utf-8')

        assert _unlisted(backend) == [source.split()[1]]

    def test_allows_listed_packages_in_any_spelling_and_the_standard_library(self, backend):
        (backend / 'app' / 'x.py').write_text(
            'import os\nfrom datetime import datetime\nimport flask\n'
            'from flask_sqlalchemy import SQLAlchemy\nfrom app.config import get_config\n'
            'from . import sibling\n',
            encoding='utf-8')

        assert _unlisted(backend) == []
