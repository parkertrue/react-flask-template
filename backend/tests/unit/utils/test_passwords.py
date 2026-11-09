from threading import BoundedSemaphore
from unittest.mock import patch

import pytest

from app.auth.models import User
from app.utils.passwords import (
    DUMMY_PASSWORD_HASH, PasswordHashingBusy, hash_password, verify_password)
from tests.conftest import register


@pytest.fixture
def slots(app, monkeypatch):
    """A single hashing slot that gives up at once, restored afterwards"""
    slot = BoundedSemaphore(1)
    monkeypatch.setitem(app.extensions, 'password_hash_slots', slot)
    monkeypatch.setitem(app.config, 'PASSWORD_HASH_WAIT_SECONDS', 0)
    return slot


def test_hash_round_trips(app):
    password_hash = hash_password('TestPassword123')

    assert verify_password(password_hash, 'TestPassword123') is True
    assert verify_password(password_hash, 'WrongPassword123') is False


def test_the_login_dummy_hash_costs_what_a_real_one_does(app):
    """An unknown email must take as long as a wrong password, even after
    the hashing cost is raised"""
    method_and_cost = DUMMY_PASSWORD_HASH.split('$')[0]

    assert method_and_cost == hash_password('TestPassword123').split('$')[0]


def test_every_worker_gets_the_configured_slots(app):
    slot = app.extensions['password_hash_slots']
    taken = [slot.acquire(blocking=False)
             for _ in range(app.config['PASSWORD_HASH_CONCURRENCY'] + 1)]
    for _ in range(sum(taken)):
        slot.release()

    assert taken == [True] * app.config['PASSWORD_HASH_CONCURRENCY'] + [False]


def test_hashing_waits_for_a_free_slot(slots):
    slots.acquire()  # another request is hashing

    with pytest.raises(PasswordHashingBusy):
        hash_password('TestPassword123')
    with pytest.raises(PasswordHashingBusy):
        verify_password('unused', 'TestPassword123')


def test_slot_is_released_when_hashing_fails(slots):
    with patch('app.utils.passwords.generate_password_hash', side_effect=ValueError):
        with pytest.raises(ValueError):
            hash_password('TestPassword123')

    assert slots.acquire(blocking=False)


def test_login_answers_503_while_every_slot_is_taken(client, sample_user, slots):
    slots.acquire()

    response = client.post(
        '/api/auth/login',
        json={'email': 'test@example.com', 'password': 'TestPassword123'})

    assert response.status_code == 503
    assert response.get_json()['error']['code'] == 'SERVICE_UNAVAILABLE'


def test_register_answers_503_without_creating_the_user(client, db, slots):
    slots.acquire()

    response = register(client, 'new@example.com')

    assert response.status_code == 503
    assert db.session.query(User).filter_by(email='new@example.com').count() == 0
