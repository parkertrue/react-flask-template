import hashlib
import hmac
from datetime import datetime, timezone

from flask import Blueprint, abort, g, request, make_response, jsonify, current_app
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from flask_jwt_extended import (
    create_access_token,
    create_refresh_token,
    current_user,
    jwt_required,
    get_jwt,
    set_refresh_cookies,
    unset_jwt_cookies,
    get_csrf_token,
    decode_token
)
from jwt.exceptions import PyJWTError
from flask_jwt_extended.exceptions import JWTExtendedException

from flask_limiter.util import get_remote_address

from app import db, limiter
from app.auth.errors import token_revoked
from app.auth.models import TERMS_VERSION, User
from app.auth.schemas import LoginRequest, RegisterRequest, normalize_email
from app.utils.errors import error_response, service_unavailable
from app.utils.log import security_event
from app.utils.passwords import DUMMY_PASSWORD_HASH, verify_password
from app.utils.redis_service import get_redis_service


auth_bp = Blueprint('auth', __name__, url_prefix='/api/auth')


def _email_digest(email: str) -> str:
    """Names one account without holding its address.

    Lowercased like MySQL's case-insensitive match on users.email, and hashed
    with SECRET_KEY: a plain hash would let anyone who reads Redis or the log
    confirm a guessed address.
    """
    secret = current_app.config['JWT_SECRET_KEY'].encode()
    return hmac.new(secret, email.lower().encode(), hashlib.sha256).hexdigest()


def _login_email_key():
    """Rate-limit key for the account being logged in to, whatever the IP.

    A per-IP limit alone either locks out everyone behind a shared address or,
    set loosely, lets one attacker guess an account's password from many. The
    email is normalized as the schema stores it, so every spelling of one
    address shares a bucket.
    """
    body = request.get_json(silent=True)
    email = body.get('email') if isinstance(body, dict) else None
    if not isinstance(email, str):
        email = ''
    try:
        email = normalize_email(email)
    except ValueError:
        # The login itself will answer 422; any key will do
        email = email.strip()
    return account_key(email)


def account_key(email: str) -> str:
    """Rate-limit key for one account, named by its email"""
    return 'email:' + _email_digest(email)


def account_password_limit(key_func, deduct_when):
    """Wrong passwords for one account, wherever they are typed: login and
    account deletion share one budget, so guesses spread over both add up.

    key_func names the account with account_key; deduct_when tells a wrong
    password from any other answer.
    """
    return limiter.shared_limit(
        '100 per hour', scope='account-password', key_func=key_func, deduct_when=deduct_when)


def _login_email_and_ip_key():
    """The account and the client's address: a lockout hits only that address"""
    return f'{_login_email_key()}:ip:{get_remote_address()}'


def _login_failed(response):
    """Only wrong passwords count toward the account limits, so the owner's
    own successful logins never use them up."""
    return response.status_code == 401


def _refresh_user_id():
    """The user a valid refresh cookie belongs to, or None.

    Limits are checked before @jwt_required runs, so the cookie is decoded
    here; decode_token checks the signature and expiry.
    """
    if 'refresh_user_id' not in g:
        g.refresh_user_id = None
        token = request.cookies.get(current_app.config['JWT_REFRESH_COOKIE_NAME'])
        if token:
            try:
                claims = decode_token(token)
            except (PyJWTError, JWTExtendedException):
                claims = {}
            if claims.get('type') == 'refresh':
                g.refresh_user_id = claims.get('sub')
    return g.refresh_user_id


def _issue_tokens(user_id: int, auth_time: int, replaces: str | None = None):
    """Build a 200 response carrying a fresh access token and refresh cookie.

    `auth_time` is when the user logged in, carried through every rotation.
    The refresh token expires SESSION_IDLE_TIMEOUT from now, so a session
    left unused that long ends, but never later than JWT_REFRESH_TOKEN_EXPIRES
    after auth_time, however often it is refreshed: a session (or a stolen
    cookie) has an absolute lifetime. Once either passes, the cookie is
    expired and refresh answers 401.

    The new refresh token's JTI is recorded in Redis, in place of the JTI in
    `replaces` when rotating; the blocklist loader treats any refresh token
    whose JTI is absent there as revoked.
    """
    now = datetime.now(timezone.utc)
    session_ends = (datetime.fromtimestamp(auth_time, timezone.utc)
                    + current_app.config['JWT_REFRESH_TOKEN_EXPIRES'])
    lifetime = min(current_app.config['SESSION_IDLE_TIMEOUT'], session_ends - now)
    access_token = create_access_token(identity=str(user_id))
    refresh_token = create_refresh_token(
        identity=str(user_id),
        additional_claims={'auth_time': auth_time},
        expires_delta=lifetime)

    redis_service = get_redis_service()
    jti = decode_token(refresh_token)['jti']
    ttl = max(int(lifetime.total_seconds()), 1)
    if redis_service is None:
        recorded = None
    elif replaces:
        recorded = redis_service.rotate_refresh_token(user_id, replaces, jti, ttl_seconds=ttl)
    else:
        recorded = redis_service.store_refresh_token(user_id, jti, ttl_seconds=ttl)

    if recorded is False:
        # Another request rotated this token between the blocklist check and
        # here; refuse it as the blocklist would have a moment later.
        security_event('refresh_refused', user_id=user_id)
        return token_revoked()
    if recorded is None:
        # A refresh token Redis never recorded counts as revoked, so the
        # session would end silently once the access token expires. Refuse
        # up front.
        return service_unavailable()

    # Only advertise a CSRF token when cookie CSRF protection is actually on;
    # IntegrationConfig turns it off for headless API tests.
    response_data = {'access_token': access_token}
    if current_app.config['JWT_COOKIE_CSRF_PROTECT']:
        response_data['refresh_csrf'] = get_csrf_token(refresh_token)

    response = make_response(jsonify(response_data), 200)
    set_refresh_cookies(response, refresh_token)
    return response


def _already_registered():
    return error_response(
        code='EMAIL_ALREADY_REGISTERED',
        message='Email already registered',
        status=409
    )


def _terms_outdated():
    return error_response(
        code='TERMS_OUTDATED',
        message='The terms have changed since this page was loaded. Reload the page to read and accept them.',
        status=409
    )


@auth_bp.route('/register', methods=['POST'])
@limiter.limit('10 per hour')
def register():
    payload = RegisterRequest.model_validate(request.get_json())

    # A page loaded before the terms changed showed the old ones, which the
    # user can no longer accept
    if payload.terms_version != TERMS_VERSION:
        return _terms_outdated()

    # A fast path that skips hashing a password for a taken email. The
    # unique index on users.email is the real check, below.
    stmt = select(User).where(User.email == payload.email)
    if db.session.execute(stmt).scalar_one_or_none():
        return _already_registered()

    user = User(email=payload.email, terms_version=payload.terms_version)
    user.set_password(payload.password)

    db.session.add(user)
    try:
        db.session.commit()
    except IntegrityError:
        # Another request registered the same email since the check above
        # (a double submit, or a client retrying)
        db.session.rollback()
        return _already_registered()

    security_event('registered', user_id=user.id)
    return jsonify({'message': 'User created'}), 201


@auth_bp.route('/login', methods=['POST'])
# Loose per IP, so a shared address keeps working.
# Tight per account and address, so a stranger's wrong guesses lock out only
# the stranger; loose per account alone, which bounds guessing spread over
# many addresses.
@limiter.limit('20 per minute')
@limiter.limit('5 per minute', key_func=_login_email_and_ip_key, deduct_when=_login_failed)
@account_password_limit(key_func=_login_email_key, deduct_when=_login_failed)
def login():
    payload = LoginRequest.model_validate(request.get_json())

    stmt = select(User).where(User.email == payload.email)
    user = db.session.execute(stmt).scalar_one_or_none()

    if user is None:
        # Hash anyway, so an unknown email takes as long as a wrong password
        verify_password(DUMMY_PASSWORD_HASH, payload.password)

    if user is None or not user.check_password(payload.password):
        # The digest is the per-account limit's key, so a guessing run on one
        # address, registered or not, can be followed across IPs
        security_event('login_failed', user_id=user.id if user else None,
                       account=_email_digest(payload.email))
        return error_response(
            code='INVALID_CREDENTIALS',
            message='Invalid email or password',
            status=401
        )

    # The password was right, even if the token store then fails (logged
    # as its own error): a takeover shows here either way
    security_event('login_succeeded', user_id=user.id)
    return _issue_tokens(user.id, auth_time=int(datetime.now(timezone.utc).timestamp()))


@auth_bp.route('/refresh', methods=['POST'])
# Per user, not per IP: everyone behind a shared address refreshes from it,
# and a 429 here would log them all out. A request without a valid cookie
# is exempt, since @jwt_required turns it away cheaply with a 401.
@limiter.limit(
    '10 per minute',
    key_func=lambda: f'user:{_refresh_user_id()}',
    exempt_when=lambda: _refresh_user_id() is None)
@jwt_required(refresh=True, locations=['cookies'])
def refresh():
    """Rotate: issue a new token pair and revoke the refresh token just used"""
    claims = get_jwt()
    return _issue_tokens(current_user.id, auth_time=claims['auth_time'], replaces=claims['jti'])


@auth_bp.route('/logout', methods=['POST'])
@jwt_required(refresh=True, locations=['cookies'])
def logout():
    user_id = current_user.id
    # The blocklist loader already refused a refresh token without a jti
    jti = get_jwt()['jti']

    redis_service = get_redis_service()
    if redis_service:
        redis_service.revoke_token(user_id, jti)
    security_event('logout', user_id=user_id)

    response = make_response(jsonify({'message': 'Logged out'}), 200)
    unset_jwt_cookies(response)
    return response


@auth_bp.route('/clear-cookies', methods=['POST'])
def clear_cookies():
    """Expire the refresh cookies when a logout request itself failed.

    They are HttpOnly, so the client cannot remove them. No token is needed,
    since logout may have failed on exactly that. Requiring a JSON body means
    another site can only send this with a CORS preflight, which it won't pass.
    """
    if not request.is_json:
        abort(415)

    response = make_response(jsonify({'message': 'Cookies cleared'}), 200)
    unset_jwt_cookies(response)
    return response


@auth_bp.route('/logout-all', methods=['POST'])
@jwt_required(refresh=True, locations=['cookies'])
def logout_all():
    """Revoke all refresh tokens for the current user (logout from all devices)"""
    # Unlike logout, this exists only for its effect on the server: other
    # devices stay signed in unless Redis drops their tokens. Report a failure
    # and keep the cookie, so the user can try again.
    redis_service = get_redis_service()
    count = redis_service.revoke_all_user_tokens(current_user.id) if redis_service else None
    if count is None:
        return service_unavailable('Could not log out other devices, please try again shortly')

    security_event('logout_all', user_id=current_user.id, sessions=count)
    message = f'Logged out from {count} device(s)' if count > 0 else 'No active sessions found'
    response = make_response(jsonify({'message': message}), 200)
    unset_jwt_cookies(response)
    return response
