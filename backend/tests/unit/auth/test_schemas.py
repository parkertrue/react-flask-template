from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from app.auth import schemas
from app.auth.models import EMAIL_MAX_LENGTH, TERMS_VERSION, User
from app.auth.schemas import (
    LINK_TOKEN_MAX_LENGTH, PASSWORD_MAX_LENGTH, PASSWORD_MIN_LENGTH, LoginRequest)

TOKEN = 'a-link-token'
# Long enough, and nothing else asked of it
PASSWORD = 'a valid passphrase'


# Named like the class it stands in for
def RegisterRequest(**fields):
    """Sign-up's two steps as one: the address goes through the first
    (RegisterRequest), the password through the second
    (RegisterCompleteRequest, with a token and the current terms), and any
    other field through both. Each test here checks one of the two."""
    first = schemas.RegisterRequest(**{k: v for k, v in fields.items() if k != 'password'})
    second = schemas.RegisterCompleteRequest(
        token=TOKEN, terms_version=TERMS_VERSION,
        **{k: v for k, v in fields.items() if k != 'email'})
    return SimpleNamespace(email=first.email, password=second.password)


def RegisterCompleteRequest(**fields):
    return schemas.RegisterCompleteRequest(**{
        'token': TOKEN, 'password': PASSWORD, 'terms_version': TERMS_VERSION, **fields})


class TestRegisterCompleteRequest:
    @pytest.mark.parametrize('field', ['token', 'password', 'terms_version'])
    def test_each_field_is_required(self, field):
        fields = {'token': TOKEN, 'password': PASSWORD, 'terms_version': TERMS_VERSION}
        del fields[field]

        with pytest.raises(ValidationError) as exc_info:
            schemas.RegisterCompleteRequest(**fields)

        assert [e['loc'] for e in exc_info.value.errors()] == [(field,)]

    @pytest.mark.parametrize('version', [str(TERMS_VERSION), float(TERMS_VERSION), True])
    def test_terms_version_must_be_an_integer(self, version):
        with pytest.raises(ValidationError):
            RegisterCompleteRequest(terms_version=version)

    def test_a_token_up_to_its_limit(self):
        token = 'a' * LINK_TOKEN_MAX_LENGTH

        assert RegisterCompleteRequest(token=token).token == token

    def test_refuses_a_longer_token(self):
        with pytest.raises(ValidationError):
            RegisterCompleteRequest(token='a' * (LINK_TOKEN_MAX_LENGTH + 1))

    def test_takes_no_email(self):
        """The token names the address: one sent beside it would be ignored"""
        with pytest.raises(ValidationError):
            RegisterCompleteRequest(email='test@example.com')


class TestRegisterRequest:
    """Sign-up's address and password, through RegisterRequest above"""

    def test_valid_registration(self):
        request = RegisterRequest(email='test@example.com', password=PASSWORD)

        assert (request.email, request.password) == ('test@example.com', PASSWORD)

    @pytest.mark.parametrize('field', ['email', 'password'])
    def test_each_is_required(self, field):
        fields = {'email': 'test@example.com', 'password': PASSWORD}
        del fields[field]

        with pytest.raises(ValidationError) as exc_info:
            RegisterRequest(**fields)

        assert [e['loc'] for e in exc_info.value.errors()] == [(field,)]

    @pytest.mark.parametrize('invalid_email', [
        'notanemail',
        '@example.com',
        'user@',
        'user @example.com',
        'user@.com',
        'user@domain',
    ])
    def test_invalid_email_format(self, invalid_email):
        with pytest.raises(ValidationError):
            RegisterRequest(email=invalid_email, password=PASSWORD)

    @pytest.mark.parametrize('valid_email', [
        'user@example.com',
        'user.name@example.com',
        'user+tag@example.com',
        'user123@sub.example.com',
        'a@b.co',
    ])
    def test_valid_email_formats(self, valid_email):
        assert RegisterRequest(email=valid_email, password=PASSWORD).email == valid_email

    def test_extra_fields_forbidden(self):
        with pytest.raises(ValidationError) as exc_info:
            RegisterRequest(email='test@example.com', password=PASSWORD, extra_field='not allowed')

        assert any('extra_forbidden' in str(e) for e in exc_info.value.errors())

    @pytest.mark.parametrize('fields', [
        {'email': None, 'password': PASSWORD}, {'email': 'test@example.com', 'password': None}])
    def test_none_values_rejected(self, fields):
        with pytest.raises(ValidationError):
            RegisterRequest(**fields)


class TestLoginRequest:
    def test_valid_login(self):
        request = LoginRequest(email='test@example.com', password=PASSWORD)

        assert (request.email, request.password) == ('test@example.com', PASSWORD)

    @pytest.mark.parametrize('fields', [{'password': PASSWORD}, {'email': 'test@example.com'}])
    def test_each_is_required(self, fields):
        with pytest.raises(ValidationError):
            LoginRequest(**fields)

    def test_invalid_email_format(self):
        with pytest.raises(ValidationError):
            LoginRequest(email='notanemail', password=PASSWORD)

    def test_extra_fields_forbidden(self):
        with pytest.raises(ValidationError):
            LoginRequest(email='test@example.com', password=PASSWORD, remember_me=True)


class TestPasswordRules:
    """One set of rules at sign-up and login alike, so a password sign-up
    refuses is never checked against an account: NIST SP 800-63B's, length
    alone, counted in characters (code points)"""

    @pytest.mark.parametrize('schema', [RegisterRequest, LoginRequest])
    @pytest.mark.parametrize('password', [
        'a' * PASSWORD_MIN_LENGTH,
        'a' * PASSWORD_MAX_LENGTH,
        'correct horse battery staple',
        'alllowercaseletters',
        '123456789012345',
        # Each emoji is one character, however many UTF-16 units it takes
        '😀' * PASSWORD_MIN_LENGTH,
        '👨‍👩‍👧 family of three',  # joined by zero-width joiners
        '🇺🇸 a flag, and a keycap 1⃣',
        'Ünïcödé pässwörd 日本語',
        '!@#$%^&*()_+-=[]{};:\'",.<>/?\\|`~',
        '©°€£¥×÷± symbols too',
        '  spaces at both ends  ',
    ])
    def test_accepts(self, schema, password):
        assert schema(email='test@example.com', password=password).password == password

    @pytest.mark.parametrize('schema', [RegisterRequest, LoginRequest])
    @pytest.mark.parametrize(('password', 'message'), [
        ('', f'at least {PASSWORD_MIN_LENGTH} characters'),
        ('a' * (PASSWORD_MIN_LENGTH - 1), f'at least {PASSWORD_MIN_LENGTH} characters'),
        ('😀' * (PASSWORD_MIN_LENGTH - 1), f'at least {PASSWORD_MIN_LENGTH} characters'),
        ('a' * (PASSWORD_MAX_LENGTH + 1), f'at most {PASSWORD_MAX_LENGTH} characters'),
    ])
    def test_refuses_the_wrong_length(self, schema, password, message):
        with pytest.raises(ValidationError, match=message):
            schema(email='test@example.com', password=password)

    # 15, written out: the tests above follow the constant wherever it moves
    @pytest.mark.parametrize('schema', [RegisterRequest, LoginRequest])
    def test_the_minimum_is_nists_for_a_single_factor(self, schema):
        with pytest.raises(ValidationError, match='at least 15 characters'):
            schema(email='test@example.com', password='a' * 14)

    @pytest.mark.parametrize('schema', [RegisterRequest, LoginRequest])
    @pytest.mark.parametrize('password', [
        PASSWORD + '\t',
        PASSWORD + '\n',
        PASSWORD + '\x00',
        PASSWORD + '\x7f',
    ], ids=['tab', 'line break', 'null', 'delete'])
    def test_refuses_control_characters(self, schema, password):
        with pytest.raises(ValidationError, match='must not contain control characters'):
            schema(email='test@example.com', password=password)

    @pytest.mark.parametrize('schema', [RegisterRequest, LoginRequest])
    def test_refuses_a_lone_surrogate(self, schema):
        """Half an emoji, which JSON can carry but UTF-8 cannot encode, so it
        could never be hashed: pydantic refuses it as no string at all"""
        with pytest.raises(ValidationError) as exc_info:
            schema(email='test@example.com', password=PASSWORD + '\ud83d')

        assert [e['type'] for e in exc_info.value.errors()] == ['string_unicode']


class TestSchemaConsistency:
    def test_email_limit_matches_column(self):
        assert EMAIL_MAX_LENGTH == User.__table__.c.email.type.length

    @pytest.mark.parametrize('schema', [RegisterRequest, LoginRequest])
    def test_email_longer_than_column_rejected(self, schema):
        email = 'a' * (EMAIL_MAX_LENGTH - len('@example.com') + 1) + '@example.com'

        with pytest.raises(ValidationError):
            schema(email=email, password=PASSWORD)

    def test_both_accept_valid_credentials(self):
        register = RegisterRequest(email='test@example.com', password=PASSWORD)
        login = LoginRequest(email='test@example.com', password=PASSWORD)

        assert (register.email, register.password) == (login.email, login.password)


class TestEmailFormat:
    """Only a plain address that any mail server can deliver to"""

    @pytest.mark.parametrize('schema', [RegisterRequest, LoginRequest])
    @pytest.mark.parametrize('email', [
        'Name <a@example.com>',     # display name
        '<a@example.com>',
        '"a b"@example.com',        # quoted local part
        'a@[192.0.2.1]',            # IP literal
        'josé@example.com',         # non-ASCII before the @ needs SMTPUTF8
        '😀@example.com',
        'a@😀.com',                  # IDNA refuses emoji in a domain
        'a@example.com‍',
    ])
    def test_rejects(self, schema, email):
        with pytest.raises(ValidationError):
            schema(email=email, password=PASSWORD)

    @pytest.mark.parametrize('schema', [RegisterRequest, LoginRequest])
    @pytest.mark.parametrize(('email', 'stored'), [
        # An international domain is kept in the ASCII form every server takes
        ('a@bücher.de', 'a@xn--bcher-kva.de'),
        ('a@xn--bcher-kva.de', 'a@xn--bcher-kva.de'),
        ('User@EXAMPLE.com', 'User@example.com'),
    ])
    def test_stores_the_ascii_form(self, schema, email, stored):
        assert schema(email=email, password=PASSWORD).email == stored

    def test_counts_the_length_of_the_stored_form(self):
        """The column holds the ASCII form, which is longer than the Unicode one"""
        domain = 'ü' * 50 + '.de'
        email = 'a' * (EMAIL_MAX_LENGTH - len(domain) - 1) + '@' + domain
        assert len(email) == EMAIL_MAX_LENGTH

        with pytest.raises(ValidationError, match=f'at most {EMAIL_MAX_LENGTH}'):
            RegisterRequest(email=email, password=PASSWORD)


class TestPasswordNormalization:
    @pytest.mark.parametrize('schema', [RegisterRequest, LoginRequest])
    @pytest.mark.parametrize(('typed', 'hashed'), [
        # é as one character, or as e plus a combining accent
        ('café au lait please', 'café au lait please'),
        ('café au lait please', 'café au lait please'),
        # Full-width letters and digits
        ('ＶalidＰassphrase１２３', 'ValidPassphrase123'),
    ])
    def test_normalizes_to_nfkc(self, schema, typed, hashed):
        assert schema(email='test@example.com', password=typed).password == hashed

    @pytest.mark.parametrize('schema', [RegisterRequest, LoginRequest])
    def test_counts_the_length_after_normalizing(self, schema):
        """ﷺ is one character that NFKC expands to eighteen"""
        assert len('ﷺ' * 8) == 8

        with pytest.raises(ValidationError, match=f'at most {PASSWORD_MAX_LENGTH}'):
            schema(email='test@example.com', password='ﷺ' * 8)

    def test_counts_the_minimum_length_after_normalizing(self):
        """3 characters as typed, but NFKC expands each ㌕ to the five of キログラム"""
        password = RegisterRequest(email='test@example.com', password='㌕' * 3).password

        assert password == 'キログラム' * 3
