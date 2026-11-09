"""Emailed links' tokens, and the links themselves"""
import time
from datetime import timedelta
from unittest.mock import patch
from urllib.parse import parse_qs, urlsplit

import pytest
from itsdangerous import TimestampSigner

from app.utils.links import LinkExpired, LinkInvalid, app_link, make_link_token, read_link_token

DAY = timedelta(days=1)


def test_a_token_names_its_address(app):
    token = make_link_token('registration', 'someone@example.com')

    assert read_link_token('registration', token, DAY) == 'someone@example.com'


def test_a_token_is_refused_for_another_purpose(app):
    """A sign-up link's token can never reset a password"""
    token = make_link_token('registration', 'someone@example.com')

    with pytest.raises(LinkInvalid):
        read_link_token('password-reset', token, DAY)


def test_a_token_is_refused_under_another_key(app, monkeypatch):
    """Rotating SECRET_KEY voids every link out"""
    token = make_link_token('registration', 'someone@example.com')
    monkeypatch.setitem(app.config, 'JWT_SECRET_KEY', 'another-key-0123456789abcdef0123')

    with pytest.raises(LinkInvalid):
        read_link_token('registration', token, DAY)


def minted_ago(age):
    then = int(time.time() - age.total_seconds())
    with patch.object(TimestampSigner, 'get_timestamp', return_value=then):
        return make_link_token('registration', 'someone@example.com')


def test_a_token_works_until_its_max_age(app):
    token = minted_ago(DAY - timedelta(seconds=5))

    assert read_link_token('registration', token, DAY) == 'someone@example.com'


def test_a_token_expires_after_its_max_age(app):
    token = minted_ago(DAY + timedelta(seconds=5))

    with pytest.raises(LinkExpired):
        read_link_token('registration', token, DAY)


@pytest.mark.parametrize('token', ['', 'garbage', 'a.b.c'])
def test_garbage_is_invalid(app, token):
    with pytest.raises(LinkInvalid):
        read_link_token('registration', token, DAY)


class TestAppLink:
    @pytest.fixture(autouse=True)
    def app_url(self, app, monkeypatch):
        monkeypatch.setitem(app.config, 'APP_URL', 'https://app.test')

    def test_a_page(self):
        assert app_link('/login') == 'https://app.test/login'

    def test_params_go_in_the_fragment_encoded(self):
        """Where no server log sees them, and an address's + survives"""
        link = urlsplit(app_link('/register/complete', email='a+b@example.com', token='t.k'))

        assert (link.path, link.query) == ('/register/complete', '')
        assert parse_qs(link.fragment) == {'email': ['a+b@example.com'], 'token': ['t.k']}
