"""Emailed links, and the tokens they carry.

A token is signed with SECRET_KEY and dated (itsdangerous), so it needs no
storage: only the email it was sent in holds it, and it expires by itself.
Each purpose signs with its own salt, so a token minted for one is refused
by every other. The token travels in the link's fragment, which no server
log sees, and the page posts it once the user acts on it (DECISIONS.md).
"""
from datetime import timedelta
from urllib.parse import urlencode

from flask import current_app
from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer


class LinkExpired(Exception):
    """A link's token is genuine, but older than its purpose allows"""


class LinkInvalid(Exception):
    """A link's token was not minted by this app for this purpose"""


def _serializer(purpose: str) -> URLSafeTimedSerializer:
    return URLSafeTimedSerializer(current_app.config['JWT_SECRET_KEY'], salt=f'link:{purpose}')


def make_link_token(purpose: str, email: str) -> str:
    """A token naming email, for a link of this purpose.

    Signed, not encrypted: the address can be read from it, which is the
    recipient's own, in a fragment no server logs.
    """
    return _serializer(purpose).dumps(email)


def read_link_token(purpose: str, token: str, max_age: timedelta) -> str:
    """The email a token of this purpose names, or LinkExpired or LinkInvalid"""
    try:
        email = _serializer(purpose).loads(token, max_age=int(max_age.total_seconds()))
    except SignatureExpired:
        raise LinkExpired() from None
    except BadSignature:
        raise LinkInvalid() from None
    if not isinstance(email, str):
        raise LinkInvalid()
    return email


def app_link(path: str, **params: str) -> str:
    """A link to one of the frontend's pages, its params in the fragment.

    Built from APP_URL, never from the request's Host header, which a client
    could set to its own site and so collect the tokens.
    """
    url = f"{current_app.config['APP_URL']}{path}"
    return f'{url}#{urlencode(params)}' if params else url
