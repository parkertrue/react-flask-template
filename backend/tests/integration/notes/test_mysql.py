"""Notes on real MySQL: column limits and ON DELETE CASCADE, which SQLite
ignores or only emulates, so unit tests cannot catch them."""
import pytest
from flask_jwt_extended import create_access_token
from sqlalchemy import delete, func, select
from sqlalchemy.exc import DataError

from app.auth.models import User
from app.notes.models import NOTE_MAX_LENGTH, Note


def test_database_rejects_an_overlong_note(integration_db, integration_user):
    """The column's size is a real limit: MySQL's strict mode refuses, not truncates"""
    integration_db.session.add(
        Note(user_id=integration_user.id, content='x' * (NOTE_MAX_LENGTH + 1)))

    with pytest.raises(DataError):
        integration_db.session.commit()
    integration_db.session.rollback()


def test_longest_note_survives_in_multibyte_characters(integration_client, integration_user):
    """The limit counts characters, not bytes: three-byte 日 fits like a letter"""
    content = '日' * NOTE_MAX_LENGTH
    token = create_access_token(identity=str(integration_user.id))
    headers = {'Authorization': f'Bearer {token}'}

    created = integration_client.post('/api/notes', json={'content': content}, headers=headers)
    listed = integration_client.get('/api/notes', headers=headers)

    assert created.status_code == 201
    assert listed.get_json()['notes'][0]['content'] == content


def test_deleting_a_user_deletes_only_their_notes(integration_db, integration_user):
    other = User(email='other@test.com')
    other.set_password('TestPassword123')
    integration_db.session.add(other)
    integration_db.session.flush()
    integration_db.session.add_all([
        Note(user_id=integration_user.id, content='mine'),
        Note(user_id=other.id, content='theirs'),
    ])
    integration_db.session.commit()

    # A bulk DELETE: the ORM never loads the notes, so only the database
    # can remove them
    integration_db.session.execute(delete(User).where(User.id == integration_user.id))
    integration_db.session.commit()

    contents = integration_db.session.execute(select(Note.content)).scalars().all()
    assert contents == ['theirs']
    assert integration_db.session.execute(select(func.count(User.id))).scalar() == 1
