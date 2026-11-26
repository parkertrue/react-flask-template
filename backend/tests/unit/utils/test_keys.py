import hashlib
import hmac
from typing import get_args

import pytest

from app.utils.keys import Purpose, keyed

SECRET = 's' * 32


def test_each_purpose_has_its_own_key():
    """What one purpose makes is never valid for another: a rate-limit key
    the app shows in Redis cannot be a job's signature"""
    digests = {purpose: keyed(SECRET, purpose, 'the same data') for purpose in get_args(Purpose)}

    assert len(set(digests.values())) == len(get_args(Purpose))


@pytest.mark.parametrize('purpose', get_args(Purpose))
def test_no_purpose_signs_with_the_secret_itself(purpose):
    # The plain HMAC this replaces, which every purpose shared
    plain = hmac.new(SECRET.encode(), b'the same data', hashlib.sha256).digest()  # noqa: TID251

    assert keyed(SECRET, purpose, 'the same data') != plain


def test_depends_on_the_secret():
    assert keyed('a' * 32, 'job', 'data') != keyed('b' * 32, 'job', 'data')


def test_is_an_hmac_sha256():
    assert len(keyed(SECRET, 'account', 'data')) == hashlib.sha256().digest_size
