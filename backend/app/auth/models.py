from datetime import datetime, timezone
from sqlalchemy.orm import Mapped, mapped_column

from app import db
from app.utils.passwords import hash_password, verify_password

# The schemas validate against this, so an over-long email is a 422, not a
# database error. frontend/src/utils/validation.js mirrors it.
EMAIL_MAX_LENGTH = 128

# The version of the terms of service a new user accepts. Raise it by one
# whenever the terms change: registering with an older one is refused, and
# each user's row records the version accepted and when.
# frontend/src/legal.js mirrors it.
TERMS_VERSION = 1


class User(db.Model):
    __tablename__ = 'users'

    id: Mapped[int] = mapped_column(primary_key=True)
    email: Mapped[str] = mapped_column(
        db.String(EMAIL_MAX_LENGTH),
        unique=True,
        nullable=False,
        index=True
    )
    password_hash: Mapped[str] = mapped_column(
        db.String(255),
        nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        db.DateTime,
        server_default=db.func.now(),
        nullable=False
    )
    terms_version: Mapped[int] = mapped_column(nullable=False)
    terms_accepted_at: Mapped[datetime] = mapped_column(
        db.DateTime,
        server_default=db.func.now(),
        nullable=False
    )

    def __init__(self, *, email: str, terms_version: int = TERMS_VERSION) -> None:
        self.email = email
        self.terms_version = terms_version

    @property
    def created_timestamp(self) -> int:
        """created_at as Unix seconds (it is stored as naive UTC); every token
        carries it, so a token cannot outlive its account (app/__init__.py)"""
        return int(self.created_at.replace(tzinfo=timezone.utc).timestamp())

    def set_password(self, password: str) -> None:
        self.password_hash = hash_password(password)

    def check_password(self, password: str) -> bool:
        return verify_password(self.password_hash, password)
