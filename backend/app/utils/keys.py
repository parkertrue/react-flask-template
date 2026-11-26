"""Every HMAC of SECRET_KEY the app makes, one key per purpose.

The app shows some of its HMACs to whoever can read Redis or the log (the
per-account rate-limit keys, the log's `account` field) and keeps others
secret (a job's signature). Made with one key, a value of one kind could
pass for another: an attacker who chose the input of a shown one could read
back a secret one. So each purpose gets its own key, an HMAC of SECRET_KEY
and the purpose's name, and nothing made for one is valid for another.

ruff bans hmac.new and its kin everywhere else (TID251), so a new HMAC of
the secret has to come through here, with a purpose of its own.
"""
import hashlib
import hmac
from typing import Literal

# job: a queued job's signature (utils/jobs.py), never shown.
# link-state: the state an emailed link carries (auth/models.py's
#   keyed_hash), readable by whoever holds the link.
# account: names an account without its address, in rate-limit keys and
#   the log (auth/routes.py's _email_digest).
Purpose = Literal['job', 'link-state', 'account']


def keyed(secret: str, purpose: Purpose, data: str) -> bytes:
    """An HMAC-SHA256 of data under the key for this purpose"""
    key = _mac(secret.encode(), b'purpose:' + purpose.encode())
    return _mac(key, data.encode())


def _mac(key: bytes, data: bytes) -> bytes:
    # The one HMAC in the app; ruff refuses one anywhere else
    return hmac.new(key, data, hashlib.sha256).digest()  # noqa: TID251
