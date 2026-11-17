import unicodedata
from typing import Annotated

from email_validator import EmailNotValidError, validate_email
from pydantic import (
    AfterValidator, BaseModel, BeforeValidator, Field, ConfigDict)

# Checked after normalizing, so the stored form always fits the users.email
# column.
from app.auth.models import EMAIL_MAX_LENGTH

# Only the hash is stored, so these are policy rather than a column size:
# NIST SP 800-63B's minimum for a password that is the only factor, and well
# above its 64 for the maximum. Counted in code points, as NIST counts.
# frontend/src/utils/validation.ts mirrors them.
PASSWORD_MIN_LENGTH = 15
PASSWORD_MAX_LENGTH = 128
# The characters no password may hold: control characters (a tab, a line
# break), which no keyboard types alike everywhere. Pydantic itself refuses
# a lone surrogate (half an emoji, which JSON can carry), which has no UTF-8
# form to hash.
PASSWORD_REFUSED_CATEGORY = 'Cc'
# The shortest part of an address before the @ that a password may not hold:
# a shorter one (jo@...) turns up in ordinary words
GUESSABLE_LOCAL_PART_MIN_LENGTH = 4
# Well above a sign-up link's token (about 100 characters), so only a body
# that is not one is refused for its length
LINK_TOKEN_MAX_LENGTH = 1024


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
    # Set whenever SMTPUTF8 is refused, as above
    ascii_email = result.ascii_email
    assert ascii_email is not None
    if len(ascii_email) > EMAIL_MAX_LENGTH:
        raise ValueError(f'Email must be at most {EMAIL_MAX_LENGTH} characters')
    return ascii_email


def is_normalized_email(value: str) -> bool:
    """Whether value is an address normalize_email accepts, already in its
    canonical form: one an emailed link or a queued job may be trusted with"""
    try:
        return normalize_email(value) == value
    except ValueError:
        return False


def _normalize_password(value: object) -> object:
    # NFKC, so the same password typed on any device hashes the same: an
    # accented letter can arrive as one character or as a letter plus a
    # combining accent, and full-width letters become plain ones. NIST SP
    # 800-63B recommends it. Done before the length checks, which then count
    # the form that is hashed.
    return unicodedata.normalize('NFKC', value) if isinstance(value, str) else value


def is_guessable(password: str, email: str, app_name: str) -> bool:
    """Whether the password holds what anyone could guess it from (ASVS
    6.2.11): the account's address, the part of it before the @ when that
    is long enough to matter, or the app's name. Ignoring case, after NFKC.
    Checked at sign-up, never at login, which accepts any password it holds.
    frontend/src/utils/validation.ts mirrors it."""
    local_part = email.partition('@')[0]
    words = [email, app_name]
    if len(local_part) >= GUESSABLE_LOCAL_PART_MIN_LENGTH:
        words.append(local_part)
    folded = unicodedata.normalize('NFKC', password).casefold()
    return any(unicodedata.normalize('NFKC', word).casefold() in folded for word in words)


def _check_password_characters(value: str) -> str:
    if any(unicodedata.category(c) == PASSWORD_REFUSED_CATEGORY for c in value):
        raise ValueError('Password must not contain control characters, such as a tab')
    return value


# Every password the app accepts, at registration, login and before a change
# only the owner may make. One set of rules, so a rule loosened in one place
# is loosened in all of them, and no password registration refuses can be
# tried anywhere. NIST SP 800-63B's: length alone, no rules on which kinds of
# character it holds; spaces and every script and emoji welcome (passphrases).
# Sign-up also refuses a guessable one (is_guessable) and a breached one
# (app/utils/breached.py).
Password = Annotated[
    str,
    # Listed first, so the length is pydantic's own check on the str (its
    # message counts characters); the BeforeValidator still runs before it,
    # so the NFKC form is what is counted
    Field(min_length=PASSWORD_MIN_LENGTH, max_length=PASSWORD_MAX_LENGTH),
    BeforeValidator(_normalize_password),
    AfterValidator(_check_password_characters),
]

# Every email the app accepts, stored and looked up in normalize_email's form
Email = Annotated[str, AfterValidator(normalize_email)]


class RegisterRequest(BaseModel):
    """Sign-up's first step: the address to send the link to"""
    email: Email

    model_config = ConfigDict(extra='forbid')


class RegisterCompleteRequest(BaseModel):
    """Sign-up's second step, from the emailed link's page"""
    # The link's token, which names the address
    token: str = Field(max_length=LINK_TOKEN_MAX_LENGTH)
    password: Password
    # The version of the terms the user saw and accepted
    terms_version: int = Field(strict=True)

    model_config = ConfigDict(extra='forbid')


class LoginRequest(BaseModel):
    email: Email
    password: Password

    model_config = ConfigDict(extra='forbid')


class TokensResponse(BaseModel):
    """A login's or refresh's new access token, and the CSRF value of the
    refresh token set in the cookie (none when CSRF protection is off)"""
    access_token: str
    refresh_csrf: str | None = None


class RegisterCompleteResponse(TokensResponse):
    """Sign-up's login, and the account's address: the token's, which the
    page signs in under, never anything else the link carried"""
    email: str
