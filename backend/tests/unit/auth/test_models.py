import string
from datetime import datetime, timezone

import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.auth.models import EMAIL_MAX_LENGTH, User, keyed_hash


class TestUserModel:
    """Test suite for User model."""

    def test_user_creation(self, db):
        """User should be created with valid data."""
        user = User(email='test@example.com')
        user.set_password('TestPassword123')
        db.session.add(user)
        db.session.commit()

        assert user.id is not None
        assert user.email == 'test@example.com'
        assert user.password_hash is not None
        assert user.created_at is not None

    def test_user_requires_email(self, db):
        """User creation should fail without email."""
        with pytest.raises(TypeError) as exc_info:
            User()

        assert 'email' in str(exc_info.value)

    def test_user_email_must_be_unique(self, db):
        """Duplicate email addresses should be rejected."""
        user1 = User(email='test@example.com')
        user1.set_password('Password123')
        db.session.add(user1)
        db.session.commit()

        user2 = User(email='test@example.com')
        user2.set_password('Password456')
        db.session.add(user2)

        with pytest.raises(IntegrityError):
            db.session.commit()

    def test_created_at_auto_generated(self, db):
        """created_at should be automatically set on creation."""
        before = datetime.now(timezone.utc).replace(microsecond=0)

        user = User(email='timestamp@example.com')
        user.set_password('Password123')
        db.session.add(user)
        db.session.commit()
        db.session.refresh(user)

        after = datetime.now(timezone.utc).replace(microsecond=0)

        # SQLite, like MySQL's DATETIME, gives it back naive
        created_at_aware = user.created_at.replace(tzinfo=timezone.utc)
        assert before <= created_at_aware <= after


class TestPasswordHashing:
    """Test password hashing functionality."""

    def test_set_password_hashes(self, db):
        """set_password should hash the password."""
        user = User(email='hash@example.com')
        password = 'PlainTextPassword123'
        user.set_password(password)

        assert user.password_hash is not None
        assert user.password_hash != password
        assert len(user.password_hash) > len(password)

    def test_password_hash_is_different_each_time(self, db):
        """Same password should generate different hashes (salt)."""
        user1 = User(email='user1@example.com')
        user2 = User(email='user2@example.com')

        same_password = 'SamePassword123'
        user1.set_password(same_password)
        user2.set_password(same_password)

        # Hashes should be different due to salt
        assert user1.password_hash != user2.password_hash

    def test_check_password_correct(self, db):
        """check_password should return True for correct password."""
        user = User(email='check@example.com')
        password = 'CorrectPassword123'
        user.set_password(password)

        assert user.check_password(password) is True

    def test_check_password_incorrect(self, db):
        """check_password should return False for incorrect password."""
        user = User(email='check@example.com')
        user.set_password('CorrectPassword123')

        assert user.check_password('WrongPassword123') is False

    def test_check_password_case_sensitive(self, db):
        """check_password should be case-sensitive."""
        user = User(email='case@example.com')
        user.set_password('Password123')

        assert user.check_password('password123') is False
        assert user.check_password('PASSWORD123') is False
        assert user.check_password('Password123') is True

    def test_password_hash_persists(self, db):
        """Password hash should persist to database."""
        user = User(email='persist@example.com')
        user.set_password('PersistPassword123')
        db.session.add(user)
        db.session.commit()

        stmt = select(User).where(User.email == 'persist@example.com')
        retrieved_user = db.session.execute(stmt).scalar_one_or_none()

        assert retrieved_user is not None
        assert retrieved_user.check_password('PersistPassword123') is True

    def test_empty_password_handling(self, db):
        """Empty password should still be hashed."""
        user = User(email='empty@example.com')
        user.set_password('')

        assert user.password_hash is not None
        assert user.password_hash != ''
        assert user.check_password('') is True

    def test_password_with_special_characters(self, db):
        """Password with special characters should work."""
        user = User(email='special@example.com')
        password = 'P@ssw0rd!#$%^&*()'
        user.set_password(password)

        assert user.check_password(password) is True
        assert user.check_password('P@ssw0rd') is False

    def test_password_with_unicode(self, db):
        """Password with Unicode characters should work."""
        user = User(email='unicode@example.com')
        password = 'Пароль123你好'
        user.set_password(password)

        assert user.check_password(password) is True

    def test_very_long_password(self, db):
        """Very long password should be handled."""
        user = User(email='long@example.com')
        password = 'A' * 1000 + '123'
        user.set_password(password)

        assert user.check_password(password) is True


class TestKeyedHash:
    """The state links and tokens carry: keyed, since a link's token can be
    read and a plain hash of the password hash could be cracked offline"""

    def test_depends_on_the_secret_key(self, app, monkeypatch):
        with app.app_context():
            ours = keyed_hash('a password hash')
            monkeypatch.setitem(app.config, 'JWT_SECRET_KEY', 'another-secret-key-of-32-characters!')
            theirs = keyed_hash('a password hash')

        assert ours != theirs

    def test_is_base64url_without_padding(self, app):
        """Not hex: a token holding hex compresses, and the link's page reads
        no address from a compressed one"""
        with app.app_context():
            state = keyed_hash('a password hash')

        assert len(state) == 43
        assert set(state) <= set(string.ascii_letters + string.digits + '-_')

    def test_names_the_account_s_password(self, app, db, sample_user):
        with app.app_context():
            assert sample_user.password_state == keyed_hash(sample_user.password_hash)


class TestUserQueries:
    """Test User model queries."""

    def test_query_by_email(self, db, sample_user):
        """Should be able to query user by email."""
        stmt = select(User).where(User.email == 'test@example.com')
        user = db.session.execute(stmt).scalar_one_or_none()

        assert user is not None
        assert user.id == sample_user.id
        assert user.email == sample_user.email

    def test_query_nonexistent_email(self, db):
        """Querying non-existent email should return None."""
        stmt = select(User).where(User.email == 'nonexistent@example.com')
        user = db.session.execute(stmt).scalar_one_or_none()

        assert user is None

    def test_query_by_id(self, db, sample_user):
        """Should be able to query user by id."""
        user = db.session.get(User, sample_user.id)

        assert user is not None
        assert user.email == sample_user.email

    def test_email_index_exists(self, db):
        """Login looks users up by email, and emails are unique"""
        from sqlalchemy import inspect

        indexes = inspect(db.engine).get_indexes('users')

        email_indexes = [idx for idx in indexes if idx['column_names'] == ['email']]
        assert len(email_indexes) == 1
        assert email_indexes[0]['unique']


class TestUserEdgeCases:
    """Test edge cases and special scenarios."""

    def test_user_with_very_long_email(self, db):
        """Email at max length should work."""
        local_part = 'a' * 119  # Max local part
        long_email = f'{local_part}@test.com'
        assert len(long_email) == EMAIL_MAX_LENGTH

        user = User(email=long_email)
        user.set_password('Password123')
        db.session.add(user)
        db.session.commit()

        assert user.email == long_email

    def test_user_with_special_email_chars(self, db):
        """Email with valid special characters should work."""
        special_email = 'user+tag@sub-domain.example.com'
        user = User(email=special_email)
        user.set_password('Password123')
        db.session.add(user)
        db.session.commit()

        assert user.email == special_email
