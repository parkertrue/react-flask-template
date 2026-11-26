import json
import re
import logging
import logging.config
import sys
from datetime import datetime
from pathlib import Path

import pytest

from app.utils import log
from app.utils.log import JsonFormatter
from tests.unit.test_app_factory import build_app

BACKEND = Path(__file__).resolve().parents[3]


def record(message='hello', exc_info=None, **fields):
    entry = logging.LogRecord('app.test', logging.WARNING, __file__, 1, message, (), exc_info)
    entry.created = datetime.fromisoformat('2026-10-13T18:02:11.250+00:00').timestamp()
    if fields:
        entry.fields = fields
    return entry


class TestJsonFormatter:
    def test_a_line_holds_the_record_and_its_fields(self):
        line = json.loads(JsonFormatter().format(record(user_id=7, ip='203.0.113.7')))

        assert line == {
            'time': '2026-10-13T18:02:11.250+00:00', 'level': 'WARNING', 'logger': 'app.test',
            'message': 'hello', 'user_id': 7, 'ip': '203.0.113.7'}

    def test_an_exception_is_kept_with_its_traceback(self):
        try:
            raise ValueError('boom')
        except ValueError:
            line = json.loads(JsonFormatter().format(record(exc_info=sys.exc_info())))

        assert line['exc'].startswith('Traceback (most recent call last):')
        assert line['exc'].endswith('ValueError: boom')

    def test_a_value_json_cannot_hold_is_written_as_text(self):
        line = json.loads(JsonFormatter().format(record(path=Path('a'))))

        assert line['path'] == 'a'


def test_the_app_logger_has_one_handler_however_many_apps_are_built(monkeypatch):
    build_app(monkeypatch)
    app = build_app(monkeypatch)

    # Flask adds its own default handler to a logger that has none
    assert app.logger.handlers == [log._handler]
    assert app.logger.level == logging.INFO


def test_the_app_logs_json_lines_on_stdout(monkeypatch, capsys):
    # Put the handler's stream back afterwards: capsys closes its own
    monkeypatch.setattr(log._handler, 'stream', log._handler.stream)
    app = build_app(monkeypatch)

    app.logger.info('started')

    line = json.loads(capsys.readouterr().out)
    assert (line['logger'], line['level'], line['message']) == ('app', 'INFO', 'started')


@pytest.mark.parametrize('headers, expected', [
    # nginx's $request_id (proxy_params.conf), which its access log holds too
    ({'X-Request-ID': '4f1c0e9a7b2d4c6e8f0a1b3c5d7e9f20'}, '4f1c0e9a7b2d4c6e8f0a1b3c5d7e9f20'),
    # Not behind nginx (dev): no field rather than an empty one
    ({}, None),
])
def test_a_line_logged_during_a_request_names_it(monkeypatch, headers, expected):
    app = build_app(monkeypatch)

    with app.test_request_context(headers=headers):
        line = json.loads(JsonFormatter().format(record()))

    assert line.get('request_id') == expected


def test_flask_limiters_warnings_are_json_lines(monkeypatch, capsys):
    """It warns when Redis is unreachable or a count fails, which would
    otherwise go nowhere"""
    monkeypatch.setattr(log._handler, 'stream', log._handler.stream)
    build_app(monkeypatch)

    logging.getLogger('flask-limiter').warning('Rate limit storage unreachable')

    line = json.loads(capsys.readouterr().out)
    assert (line['logger'], line['message']) == ('flask-limiter', 'Rate limit storage unreachable')


def test_gunicorns_own_lines_are_json_lines(monkeypatch, capsys):
    """backend/Dockerfile passes gunicorn_logging.json, so a WORKER TIMEOUT or
    a boot failure parses like every other line. Gunicorn applies the file
    with dictConfig over defaults that put a plain-text handler on the root;
    the file's root has none, or every app line would be written twice.
    (gunicorn itself cannot be imported on Windows; CI's E2E job checks
    the running container's lines.)"""
    monkeypatch.setattr(log._handler, 'stream', log._handler.stream)
    app = build_app(monkeypatch)
    # dictConfig replaces these loggers' handlers: give them back afterwards
    for logger in (logging.getLogger(), logging.getLogger('gunicorn.error')):
        for name in ('handlers', 'level', 'propagate'):
            monkeypatch.setattr(logger, name, getattr(logger, name))
        logger.handlers = [logging.StreamHandler(sys.stdout)]  # as gunicorn's defaults
    config = json.loads((BACKEND / 'gunicorn_logging.json').read_text())

    logging.config.dictConfig(config)
    logging.getLogger('gunicorn.error').critical('WORKER TIMEOUT (pid:%s)', 9)
    app.logger.warning('Database unavailable')

    lines = [json.loads(line) for line in capsys.readouterr().out.splitlines()]
    assert [(line['logger'], line['level'], line['message']) for line in lines] == [
        ('gunicorn.error', 'CRITICAL', 'WORKER TIMEOUT (pid:9)'),
        ('app', 'WARNING', 'Database unavailable'),
    ]


def logged_events():
    """Every event name the app logs by name: those a security_event call
    passes, and the worker's, logged on its logger directly (job_refused)"""
    sources = (BACKEND / 'app').rglob('*.py')
    pattern = r"(?:security_event|\blog\.\w+)\(\s*'(\w+)'"
    return sorted({name for source in sources
                   for name in re.findall(pattern, source.read_text(encoding='utf-8'))})


@pytest.mark.parametrize('doc', ['docs/deployment.md', 'CLAUDE.md'])
def test_every_security_event_is_documented(doc):
    """An operator reads the events' names there to search the log for
    them; one left out goes unwatched"""
    text = (BACKEND.parent / doc).read_text(encoding='utf-8')

    missing = [name for name in logged_events() if f'`{name}`' not in text]

    assert missing == []


def test_the_app_logs_security_events():
    """The search above finds the calls, so an empty list cannot pass it"""
    assert 'login_failed' in logged_events()
