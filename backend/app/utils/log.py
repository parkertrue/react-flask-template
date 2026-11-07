"""The app's log: one JSON object per line, on stdout.

Docker collects stdout, and a log shipper parses a JSON line without a
pattern. Security events go through security_event, on the app.security
logger, so they can be picked out by name. Requests are logged once, by
nginx, whose access log is JSON too; a line logged during a request carries
nginx's request_id, which joins it to that request's access-log line.
Gunicorn's own lines use JsonFormatter too (gunicorn_logging.json).
"""
import json
import logging
import sys
from datetime import datetime, timezone

from flask import Flask, current_app, has_request_context, request


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        line = {
            'time': datetime.fromtimestamp(record.created, timezone.utc)
            .isoformat(timespec='milliseconds'),
            'level': record.levelname,
            'logger': record.name,
            'message': record.getMessage(),
            **getattr(record, 'fields', {}),
        }
        # Set by nginx (proxy_params.conf); absent in dev, where Vite proxies
        if has_request_context() and 'X-Request-ID' in request.headers:
            line['request_id'] = request.headers['X-Request-ID']
        if record.exc_info:
            line['exc'] = self.formatException(record.exc_info)
        return json.dumps(line, default=str)


_handler = logging.StreamHandler(sys.stdout)
_handler.setFormatter(JsonFormatter())


def configure_logging(app: Flask) -> None:
    """Send the app's logger, and so every logger under it, to stdout as JSON.

    Only the app's own logger, not the root: libraries stay quiet, and a
    handler the root already has (pytest's caplog) keeps receiving records.
    With a handler in place, Flask adds no default one of its own.
    Flask-Limiter logs its own warnings (Redis unreachable, a failed count),
    which would otherwise reach stderr as plain text.
    """
    # stdout as it is now, which a test may have swapped for its own
    _handler.setStream(sys.stdout)
    for name in (app.name, 'flask-limiter'):
        logger = logging.getLogger(name)
        logger.addHandler(_handler)  # a no-op when the logger already has it
        logger.setLevel(logging.INFO)


def security_event(event: str, **fields: object) -> None:
    """Log something an investigation would need (a login, a refused token,
    a rate limit hit) with the client's address.

    Pass ids, never a password, token, CSRF value or email: the log is kept
    and read by more people than the database.
    """
    current_app.logger.getChild('security').info(
        event, extra={'fields': {'ip': request.remote_addr, **fields}})
