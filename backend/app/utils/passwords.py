from collections.abc import Iterator
from contextlib import contextmanager
from threading import BoundedSemaphore

from flask import Flask, current_app
from werkzeug.security import check_password_hash, generate_password_hash


# Werkzeug's default spelled out, scrypt:32768:8:1 today. Raise the cost here
# (DECISIONS.md, on production hardware) and the dummy hash below follows.
PASSWORD_HASH_METHOD = 'scrypt'

# Login checks an unknown email against this, so it takes as long as a wrong
# password and response timing doesn't reveal which emails are registered
DUMMY_PASSWORD_HASH = generate_password_hash('not-a-real-password', method=PASSWORD_HASH_METHOD)


class PasswordHashingBusy(Exception):
    """No hashing slot came free within PASSWORD_HASH_WAIT_SECONDS"""


def init_password_hashing(app: Flask) -> None:
    """Give this worker its hashing slots.

    A hash costs ~75ms of CPU. Without a cap, a burst of logins takes every
    gunicorn thread and every other request waits behind them; with one,
    the remaining threads keep serving the rest of the API.
    """
    app.extensions['password_hash_slots'] = BoundedSemaphore(
        app.config['PASSWORD_HASH_CONCURRENCY'])


@contextmanager
def _hash_slot() -> Iterator[None]:
    slots = current_app.extensions['password_hash_slots']
    if not slots.acquire(timeout=current_app.config['PASSWORD_HASH_WAIT_SECONDS']):
        raise PasswordHashingBusy()
    try:
        yield
    finally:
        slots.release()


def hash_password(password: str) -> str:
    with _hash_slot():
        return generate_password_hash(password, method=PASSWORD_HASH_METHOD)


def verify_password(password_hash: str, password: str) -> bool:
    with _hash_slot():
        return check_password_hash(password_hash, password)
