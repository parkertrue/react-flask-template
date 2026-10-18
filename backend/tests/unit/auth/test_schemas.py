import pytest
from pydantic import ValidationError

from app.auth import schemas
from app.auth.models import EMAIL_MAX_LENGTH, TERMS_VERSION, User
from app.auth.schemas import PASSWORD_MAX_LENGTH, LoginRequest


# Named like the class it stands in for
def RegisterRequest(**fields):
    """The register schema with the current terms accepted, which every test
    here takes as given but TestTermsVersion's"""
    return schemas.RegisterRequest(terms_version=TERMS_VERSION, **fields)


class TestTermsVersion:
    def test_is_required(self):
        with pytest.raises(ValidationError):
            schemas.RegisterRequest(email='test@example.com', password='ValidPass123')

    @pytest.mark.parametrize('version', [str(TERMS_VERSION), float(TERMS_VERSION), True])
    def test_must_be_an_integer(self, version):
        with pytest.raises(ValidationError):
            schemas.RegisterRequest(
                email='test@example.com', password='ValidPass123', terms_version=version)


class TestRegisterRequest:
    """Test suite for RegisterRequest schema."""

    def test_valid_registration(self):
        """Schema should accept valid registration data."""
        data = {
            'email': 'test@example.com',
            'password': 'ValidPass123'
        }
        request = RegisterRequest(**data)

        assert request.email == 'test@example.com'
        assert request.password == 'ValidPass123'

    def test_missing_email(self):
        """Schema should reject missing email."""
        with pytest.raises(ValidationError) as exc_info:
            RegisterRequest(password='ValidPass123')

        errors = exc_info.value.errors()
        assert any(e['loc'] == ('email',) for e in errors)

    def test_missing_password(self):
        """Schema should reject missing password."""
        with pytest.raises(ValidationError) as exc_info:
            RegisterRequest(email='test@example.com')

        errors = exc_info.value.errors()
        assert any(e['loc'] == ('password',) for e in errors)

    @pytest.mark.parametrize('invalid_email', [
        'notanemail',
        '@example.com',
        'user@',
        'user @example.com',
        'user@.com',
        'user@domain',
    ])
    def test_invalid_email_format(self, invalid_email):
        """Schema should reject invalid email formats."""
        with pytest.raises(ValidationError):
            RegisterRequest(
                email=invalid_email,
                password='ValidPass123'
            )

    @pytest.mark.parametrize('valid_email', [
        'user@example.com',
        'user.name@example.com',
        'user+tag@example.com',
        'user123@sub.example.com',
        'a@b.co',
    ])
    def test_valid_email_formats(self, valid_email):
        """Schema should accept various valid email formats."""
        request = RegisterRequest(
            email=valid_email,
            password='ValidPass123'
        )
        assert request.email == valid_email

    @pytest.mark.parametrize('password', ['Pass1', 'Ab1', 'Short7'])
    def test_password_min_length(self, password):
        """Schema should reject passwords under 8 characters."""
        with pytest.raises(ValidationError) as exc_info:
            RegisterRequest(
                email='test@example.com',
                password=password
            )

        errors = exc_info.value.errors()
        assert any('min_length' in str(e) for e in errors)

    def test_password_max_length(self):
        """Schema should reject passwords over 128 characters."""
        # 129 characters
        long_password = 'A1' + 'a' * 127

        with pytest.raises(ValidationError) as exc_info:
            RegisterRequest(
                email='test@example.com',
                password=long_password
            )

        errors = exc_info.value.errors()
        assert any('max_length' in str(e) for e in errors)

    def test_password_exactly_8_chars(self):
        """Schema should accept password with exactly 8 characters."""
        request = RegisterRequest(
            email='test@example.com',
            password='Valid123'
        )
        assert len(request.password) == 8

    def test_password_exactly_128_chars(self):
        """Schema should accept password with exactly 128 characters."""
        # 128 characters with uppercase, lowercase, and digit
        password = 'A1' + 'a' * 126
        request = RegisterRequest(
            email='test@example.com',
            password=password
        )
        assert len(request.password) == 128

    def test_password_requires_uppercase(self):
        """Schema should reject passwords without uppercase letter."""
        with pytest.raises(ValidationError) as exc_info:
            RegisterRequest(
                email='test@example.com',
                password='lowercase123'
            )

        errors = exc_info.value.errors()
        error_messages = [str(e) for e in errors]
        assert any('uppercase' in msg.lower() for msg in error_messages)

    def test_password_requires_lowercase(self):
        """Schema should reject passwords without lowercase letter."""
        with pytest.raises(ValidationError) as exc_info:
            RegisterRequest(
                email='test@example.com',
                password='UPPERCASE123'
            )

        errors = exc_info.value.errors()
        error_messages = [str(e) for e in errors]
        assert any('lowercase' in msg.lower() for msg in error_messages)

    def test_password_requires_number(self):
        """Schema should reject passwords without number."""
        with pytest.raises(ValidationError) as exc_info:
            RegisterRequest(
                email='test@example.com',
                password='NoNumbersHere'
            )

        errors = exc_info.value.errors()
        error_messages = [str(e) for e in errors]
        assert any('number' in msg.lower() for msg in error_messages)

    @pytest.mark.parametrize('password', [
        'ValidPass123',
        'Abcdefg1',
        'P@ssw0rd',
        'MyPassword1',
        'Test1234',
    ])
    def test_password_with_all_requirements(self, password):
        """Schema should accept password meeting all requirements."""
        request = RegisterRequest(
            email='test@example.com',
            password=password
        )
        assert request.password == password

    def test_password_with_special_characters(self):
        """Schema should accept passwords with special characters."""
        password = 'P@ssw0rd!#$%'
        request = RegisterRequest(
            email='test@example.com',
            password=password
        )
        assert request.password == password

    def test_extra_fields_forbidden(self):
        """Schema should reject extra fields."""
        with pytest.raises(ValidationError) as exc_info:
            RegisterRequest(
                email='test@example.com',
                password='ValidPass123',
                extra_field='not allowed'
            )

        errors = exc_info.value.errors()
        assert any('extra_forbidden' in str(e) for e in errors)

    def test_none_values_rejected(self):
        """Schema should reject None values."""
        with pytest.raises(ValidationError):
            RegisterRequest(email=None, password='ValidPass123')

        with pytest.raises(ValidationError):
            RegisterRequest(email='test@example.com', password=None)

    def test_model_dump(self):
        """Schema should serialize to dict correctly."""
        request = RegisterRequest(
            email='test@example.com',
            password='ValidPass123'
        )
        data = request.model_dump()

        assert data['email'] == 'test@example.com'
        assert data['password'] == 'ValidPass123'

    def test_model_dump_excludes_password(self):
        """model_dump includes the password unless excluded."""
        request = RegisterRequest(
            email='test@example.com',
            password='ValidPass123'
        )

        data = request.model_dump()
        assert 'password' in data

        data_safe = request.model_dump(exclude={'password'})
        assert 'password' not in data_safe
        assert 'email' in data_safe


class TestLoginRequest:
    """Test suite for LoginRequest schema."""

    def test_valid_login(self):
        """Schema should accept valid login data."""
        data = {
            'email': 'test@example.com',
            'password': 'ValidPass123'
        }
        request = LoginRequest(**data)

        assert request.email == 'test@example.com'
        assert request.password == 'ValidPass123'

    def test_missing_email(self):
        """Schema should reject missing email."""
        with pytest.raises(ValidationError):
            LoginRequest(password='ValidPass123')

    def test_missing_password(self):
        """Schema should reject missing password."""
        with pytest.raises(ValidationError):
            LoginRequest(email='test@example.com')

    def test_invalid_email_format(self):
        """Schema should reject invalid email format."""
        with pytest.raises(ValidationError):
            LoginRequest(
                email='notanemail',
                password='ValidPass123'
            )

    def test_empty_password_rejected(self):
        with pytest.raises(ValidationError):
            LoginRequest(email='test@example.com', password='')

    def test_password_max_length(self):
        """Schema should enforce maximum password length."""
        long_password = 'a' * 129

        with pytest.raises(ValidationError):
            LoginRequest(
                email='test@example.com',
                password=long_password
            )

    def test_extra_fields_forbidden(self):
        """Schema should reject extra fields."""
        with pytest.raises(ValidationError):
            LoginRequest(
                email='test@example.com',
                password='ValidPass123',
                remember_me=True
            )

    def test_model_dump(self):
        """Schema should serialize to dict correctly."""
        request = LoginRequest(
            email='test@example.com',
            password='ValidPass123'
        )
        data = request.model_dump()

        assert data['email'] == 'test@example.com'
        assert data['password'] == 'ValidPass123'


class TestSchemaConsistency:
    """Test consistency between registration and login schemas."""

    def test_email_limit_matches_column(self):
        assert EMAIL_MAX_LENGTH == User.__table__.c.email.type.length

    @pytest.mark.parametrize('schema', [RegisterRequest, LoginRequest])
    def test_email_longer_than_column_rejected(self, schema):
        email = 'a' * (EMAIL_MAX_LENGTH - len('@example.com') + 1) + '@example.com'

        with pytest.raises(ValidationError):
            schema(email=email, password='ValidPass123')

    def test_both_accept_valid_credentials(self):
        """Valid credentials should work for both register and login."""
        email = 'test@example.com'
        password = 'ValidPass123'

        register = RegisterRequest(email=email, password=password)
        login = LoginRequest(email=email, password=password)

        assert register.email == login.email
        assert register.password == login.password

    @pytest.mark.parametrize('schema', [RegisterRequest, LoginRequest])
    @pytest.mark.parametrize(('password', 'message'), [
        ('Pass123', 'at least 8 characters'),
        ('testpassword123', 'must contain uppercase letter'),
        ('TESTPASSWORD123', 'must contain lowercase letter'),
        ('TestPassword', 'must contain number'),
    ])
    def test_both_apply_the_strength_rules(self, schema, password, message):
        """Login refuses what registration would, so no password registration
        refuses is ever checked against an account"""
        with pytest.raises(ValidationError, match=message):
            schema(email='test@example.com', password=password)

    def test_password_length_consistency(self):
        """Both schemas should have same password length requirements."""
        password_8 = 'Valid123'

        RegisterRequest(email='test@example.com', password=password_8)
        LoginRequest(email='test@example.com', password=password_8)

        password_128 = 'A1' + 'a' * 126

        RegisterRequest(email='test@example.com', password=password_128)
        LoginRequest(email='test@example.com', password=password_128)

        password_129 = 'A1' + 'a' * 127

        with pytest.raises(ValidationError):
            RegisterRequest(email='test@example.com', password=password_129)

        with pytest.raises(ValidationError):
            LoginRequest(email='test@example.com', password=password_129)


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
        'a@example.com\u200d',
    ])
    def test_rejects(self, schema, email):
        with pytest.raises(ValidationError):
            schema(email=email, password='ValidPass123')

    @pytest.mark.parametrize('schema', [RegisterRequest, LoginRequest])
    @pytest.mark.parametrize(('email', 'stored'), [
        # An international domain is kept in the ASCII form every server takes
        ('a@bücher.de', 'a@xn--bcher-kva.de'),
        ('a@xn--bcher-kva.de', 'a@xn--bcher-kva.de'),
        ('User@EXAMPLE.com', 'User@example.com'),
    ])
    def test_stores_the_ascii_form(self, schema, email, stored):
        assert schema(email=email, password='ValidPass123').email == stored

    def test_counts_the_length_of_the_stored_form(self):
        """The column holds the ASCII form, which is longer than the Unicode one"""
        domain = 'ü' * 50 + '.de'
        email = 'a' * (EMAIL_MAX_LENGTH - len(domain) - 1) + '@' + domain
        assert len(email) == EMAIL_MAX_LENGTH

        with pytest.raises(ValidationError, match=f'at most {EMAIL_MAX_LENGTH}'):
            RegisterRequest(email=email, password='ValidPass123')


class TestPasswordCharacters:
    """The same characters at login as at sign-up"""

    @pytest.mark.parametrize('schema', [RegisterRequest, LoginRequest])
    @pytest.mark.parametrize('password', [
        'Valid Pass123',            # space
        'ValidPass123\t',
        'Valid\u00a0Pass123',       # no-break space
        'Valid\u3000Pass123',       # ideographic space
    ])
    def test_rejects_spaces(self, schema, password):
        with pytest.raises(ValidationError, match='must not contain spaces'):
            schema(email='test@example.com', password=password)

    @pytest.mark.parametrize('schema', [RegisterRequest, LoginRequest])
    @pytest.mark.parametrize('password', [
        'ValidPass123😀',
        'ValidPass123🚀',
        'ValidPass123\u2764',        # heavy heart, a symbol emoji
        'ValidPass123\U0001F1FA\U0001F1F8',  # a flag: regional indicators
        'ValidPass1\u20e3',          # keycap: 1 + combining enclosing keycap
        'ValidPass123\ufe0f',        # emoji variation selector
        'ValidPass123\U0001F3FB',    # skin-tone modifier
        'ValidPass123\u200d',        # zero-width joiner
        'ValidPass123\U00020000',    # a CJK letter beyond the Basic Multilingual Plane
        'ValidPass123©',
        'ValidPass123°',
    ])
    def test_rejects_emoji_and_other_symbols(self, schema, password):
        with pytest.raises(ValidationError, match='must not contain emoji'):
            schema(email='test@example.com', password=password)

    @pytest.mark.parametrize('schema', [RegisterRequest, LoginRequest])
    @pytest.mark.parametrize('password', [
        'ValidPass123!@#$%^&*()_+-=[]{};:\'",.<>/?\\|`~',
        'ValidPass123€£¥',
        'ValidPass123éßøñ',
        'ValidPass123日本語',
        'ValidPass123×÷±',
    ])
    def test_accepts_letters_punctuation_and_symbols_of_any_language(self, schema, password):
        assert schema(email='test@example.com', password=password).password == password


class TestPasswordNormalization:
    @pytest.mark.parametrize('schema', [RegisterRequest, LoginRequest])
    @pytest.mark.parametrize(('typed', 'hashed'), [
        # é as one character, or as e plus a combining accent
        ('Caf\u00e9Pass123', 'Caf\u00e9Pass123'),
        ('Cafe\u0301Pass123', 'Caf\u00e9Pass123'),
        # Full-width letters and digits
        ('\uff36alid\uff30ass\uff11\uff12\uff13', 'ValidPass123'),
    ])
    def test_normalizes_to_nfkc(self, schema, typed, hashed):
        assert schema(email='test@example.com', password=typed).password == hashed

    @pytest.mark.parametrize('schema', [RegisterRequest, LoginRequest])
    def test_counts_the_length_after_normalizing(self, schema):
        """\ufdfa is one character that NFKC expands to eighteen"""
        assert len('Aa1' + '\ufdfa' * 8) == 11

        with pytest.raises(ValidationError, match=f'at most {PASSWORD_MAX_LENGTH}'):
            schema(email='test@example.com', password='Aa1' + '\ufdfa' * 8)

    def test_counts_the_minimum_length_after_normalizing(self):
        """4 characters as typed, but NFKC expands \u3315 to the five of \u30ad\u30ed\u30b0\u30e9\u30e0"""
        password = RegisterRequest(email='test@example.com', password='Aa1\u3315').password

        assert password == 'Aa1\u30ad\u30ed\u30b0\u30e9\u30e0'
