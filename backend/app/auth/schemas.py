import re
import unicodedata
from typing import Annotated

from email_validator import EmailNotValidError, validate_email
from pydantic import (
    AfterValidator, BaseModel, BeforeValidator, Field, ConfigDict)

# Checked after normalizing, so the stored form always fits the users.email
# column.
from app.auth.models import EMAIL_MAX_LENGTH
from app.utils.text import UNSUPPORTED_CHARACTERS_MESSAGE, is_plain_text

# Only the hash is stored, so these are policy rather than a column size.
# frontend/src/utils/validation.js mirrors them.
PASSWORD_MIN_LENGTH = 8
PASSWORD_MAX_LENGTH = 128


def normalize_email(value: str) -> str:
    """The canonical, ASCII-only form of an email address, or ValueError.

    Only a plain local@domain.tld address passes: no display name, quoting
    or IP literal. The part before the @ must be ASCII, so any mail server
    can deliver to it (non-ASCII there needs SMTPUTF8, which many lack).
    An international domain is allowed and stored as its ASCII form
    (bücher.de -> xn--bcher-kva.de), which every server accepts and which
    keeps one mailbox to one account. IDNA refuses emoji in a domain.
    """
    try:
        result = validate_email(value, allow_smtputf8=False, check_deliverability=False)
    except EmailNotValidError as e:
        raise ValueError(str(e)) from None
    if len(result.ascii_email) > EMAIL_MAX_LENGTH:
        raise ValueError(f'Email must be at most {EMAIL_MAX_LENGTH} characters')
    return result.ascii_email


def _normalize_password(value):
    # NFKC, so the same password typed on any device hashes the same: an
    # accented letter can arrive as one character or as a letter plus a
    # combining accent, and full-width letters become plain ones. NIST SP
    # 800-63B recommends it. Done before the length checks, which then count
    # the form that is hashed.
    return unicodedata.normalize('NFKC', value) if isinstance(value, str) else value


def _check_password_characters(value: str) -> str:
    if any(c.isspace() for c in value):
        raise ValueError('Password must not contain spaces')
    if not is_plain_text(value):
        raise ValueError(f'Password {UNSUPPORTED_CHARACTERS_MESSAGE}')
    return value


def _check_strength(value: str) -> str:
    if not re.search(r'[A-Z]', value):
        raise ValueError('Password must contain uppercase letter')
    if not re.search(r'[a-z]', value):
        raise ValueError('Password must contain lowercase letter')
    if not re.search(r'[0-9]', value):
        raise ValueError('Password must contain number')
    return value


# Every password the app accepts, at registration, login and before a change
# only the owner may make. One set of rules, so a rule loosened in one place
# is loosened in all of them, and no password registration refuses can be
# tried anywhere.
Password = Annotated[
    str,
    # Before the validator, so pydantic counts characters (its message says
    # so); the validator still runs first
    Field(min_length=PASSWORD_MIN_LENGTH, max_length=PASSWORD_MAX_LENGTH),
    BeforeValidator(_normalize_password),
    AfterValidator(_check_password_characters),
    AfterValidator(_check_strength),
]

# Every email the app accepts, stored and looked up in normalize_email's form
Email = Annotated[str, AfterValidator(normalize_email)]


class RegisterRequest(BaseModel):
    email: Email
    password: Password
    # The version of the terms the user saw and accepted
    terms_version: int = Field(strict=True)

    model_config = ConfigDict(extra='forbid')


class LoginRequest(BaseModel):
    email: Email
    password: Password

    model_config = ConfigDict(extra='forbid')
