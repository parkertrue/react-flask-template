import pytest
from datetime import datetime, timezone
from sqlalchemy import delete, event, func, select
from sqlalchemy.exc import IntegrityError

from app.auth.models import User
from app.notes.models import Note


class TestNoteModel:
    """Test suite for Note model."""

    def test_note_creation(self, db, sample_user):
        """Note should be created with valid data."""
        note = Note(
            user_id=sample_user.id,
            content='Test note content'
        )
        db.session.add(note)
        db.session.commit()

        assert note.id is not None
        assert note.user_id == sample_user.id
        assert note.content == 'Test note content'
        assert note.created_at is not None

    def test_note_requires_user_id(self, db):
        """Note creation should fail without user_id."""
        with pytest.raises(TypeError) as exc_info:
            Note(content='Content without user')

        assert 'user_id' in str(exc_info.value)

    def test_note_requires_content(self, db, sample_user):
        """Note creation should fail without content."""
        with pytest.raises(TypeError) as exc_info:
            Note(user_id=sample_user.id)

        assert 'content' in str(exc_info.value)

    def test_note_created_at_auto_generated(self, db, sample_user):
        """created_at should be automatically set on creation."""
        before = datetime.now(timezone.utc).replace(microsecond=0)

        note = Note(
            user_id=sample_user.id,
            content='Auto timestamp test'
        )
        db.session.add(note)
        db.session.commit()
        db.session.refresh(note)

        after = datetime.now(timezone.utc).replace(microsecond=0)

        # SQLite returns DATETIME naive, and the column holds UTC
        assert before <= note.created_at.replace(tzinfo=timezone.utc) <= after

    def test_note_foreign_key_constraint(self, db):
        """Note should not allow invalid user_id."""
        note = Note(
            user_id=99999,  # Non-existent user
            content='Invalid user note'
        )
        db.session.add(note)

        with pytest.raises(IntegrityError):
            db.session.commit()

    def test_note_content_max_length(self, db, sample_user):
        """Note content should respect max length constraint."""
        content_256 = 'x' * 256
        note = Note(user_id=sample_user.id, content=content_256)
        db.session.add(note)
        db.session.commit()

        assert note.content == content_256

    def test_multiple_notes_per_user(self, db, sample_user):
        """User should be able to have multiple notes."""
        notes = [
            Note(user_id=sample_user.id, content=f'Note {i}')
            for i in range(5)
        ]
        db.session.add_all(notes)
        db.session.commit()

        stmt = select(Note).where(Note.user_id == sample_user.id)
        user_notes = db.session.execute(stmt).scalars().all()

        assert len(user_notes) == 5

    def test_notes_from_different_users(self, db, sample_user, second_user):
        """Different users should have separate notes."""
        note1 = Note(user_id=sample_user.id, content='User 1 note')
        note2 = Note(user_id=second_user.id, content='User 2 note')

        db.session.add_all([note1, note2])
        db.session.commit()

        stmt1 = select(Note).where(Note.user_id == sample_user.id)
        stmt2 = select(Note).where(Note.user_id == second_user.id)

        user1_notes = db.session.execute(stmt1).scalars().all()
        user2_notes = db.session.execute(stmt2).scalars().all()

        assert len(user1_notes) == 1
        assert len(user2_notes) == 1
        assert user1_notes[0].content == 'User 1 note'
        assert user2_notes[0].content == 'User 2 note'

    def test_deleting_a_user_deletes_their_notes_in_the_database(
            self, db, sample_user, second_user, sample_notes):
        """ON DELETE CASCADE, not the ORM: a bulk DELETE never loads the notes"""
        other = Note(user_id=second_user.id, content='Not mine')
        db.session.add(other)
        db.session.commit()

        db.session.execute(delete(User).where(User.id == sample_user.id))
        db.session.commit()

        remaining = db.session.execute(select(Note.content)).scalars().all()
        assert remaining == ['Not mine']

    def test_deleting_a_user_does_not_load_their_notes(self, db, sample_user, sample_notes):
        """One DELETE on users, nothing per note: the database cascades, so
        nothing on User may make the ORM load a user's rows to delete them"""
        db.session.expire_all()
        user = db.session.get(User, sample_user.id)
        statements = []
        engine = db.engine

        def record(conn, cursor, statement, *args):
            statements.append(statement)

        event.listen(engine, 'before_cursor_execute', record)
        try:
            db.session.delete(user)
            db.session.commit()
        finally:
            event.remove(engine, 'before_cursor_execute', record)

        assert not any(s.lstrip().upper().startswith('SELECT') and 'notes' in s
                       for s in statements)
        assert db.session.execute(select(func.count(Note.id))).scalar() == 0

    def test_note_with_special_characters(self, db, sample_user):
        """Note should handle special characters in content."""
        special_content = "Special: <>&\"'(){}[]!@#$%"
        note = Note(user_id=sample_user.id, content=special_content)
        db.session.add(note)
        db.session.commit()
        db.session.refresh(note)

        assert note.content == special_content

    def test_note_with_unicode(self, db, sample_user):
        """Note should handle Unicode characters."""
        unicode_content = 'Unicode: 你好 مرحبا שלום'
        note = Note(user_id=sample_user.id, content=unicode_content)
        db.session.add(note)
        db.session.commit()
        db.session.refresh(note)

        assert note.content == unicode_content

    def test_note_with_empty_string(self, db, sample_user):
        """The column takes an empty string; NoteCreateRequest is what refuses one."""
        note = Note(user_id=sample_user.id, content='')
        db.session.add(note)
        db.session.commit()
        assert note.content == ''
