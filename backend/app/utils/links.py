"""Emailed links, and the tokens they carry.

A token is signed with SECRET_KEY and dated (itsdangerous), so it needs no
storage: only the email it was sent in holds it, and it expires by itself.
Each purpose signs with its own salt, so a token minted for one is refused
by every other. The token travels in the link's fragment, which no server
log sees, and the page posts it once the user acts on it (DECISIONS.md).

A token can also carry a state: what its purpose needs to stay true for the
link to work (a password reset's, the password it replaces), which the
caller compares with the present one.
"""
from datetime import timedelta
from typing import NamedTuple
from urllib.parse import urlencode

from flask import current_app
from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer


class LinkExpired(Exception):
    """A link's token is genuine, but older than its purpose allows"""


class LinkInvalid(Exception):
    """A link's token was not minted by this app for this purpose"""


class LinkClaims(NamedTuple):
    """What a link's token names: an address, and the state it was minted in"""
    email: str
    state: str


def _serializer(purpose: str) -> URLSafeTimedSerializer:
    return URLSafeTimedSerializer(current_app.config['JWT_SECRET_KEY'], salt=f'link:{purpose}')


def make_link_token(purpose: str, email: str, state: str = '') -> str:
    """A token naming email, and state, for a link of this purpose.

    Signed, not encrypted: both can be read from it. The address is the
    recipient's own, in a fragment no server logs; a state must reveal
    nothing (a keyed hash, never a secret itself).
    """
    return _serializer(purpose).dumps([email, state])


def read_link_token(purpose: str, token: str, max_age: timedelta) -> LinkClaims:
    """What a token of this purpose names, or LinkExpired or LinkInvalid"""
    try:
        claims = _serializer(purpose).loads(token, max_age=int(max_age.total_seconds()))
    except SignatureExpired:
        raise LinkExpired() from None
    except BadSignature:
        raise LinkInvalid() from None
    match claims:
        case [str(email), str(state)]:
            return LinkClaims(email, state)
        case _:
            raise LinkInvalid()


def app_link(path: str, **params: str) -> str:
    """A link to one of the frontend's pages, its params in the fragment.

    Built from APP_URL, never from the request's Host header, which a client
    could set to its own site and so collect the tokens.
    """
    url = f"{current_app.config['APP_URL']}{path}"
    return f'{url}#{urlencode(params)}' if params else url
