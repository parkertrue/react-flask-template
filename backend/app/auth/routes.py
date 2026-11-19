import hashlib
import hmac
import secrets
from datetime import datetime, timedelta, timezone

from collections.abc import Callable
from typing import Any, cast

from flask import Blueprint, Response, abort, g, request, make_response, jsonify, current_app
from flask.typing import ResponseReturnValue
from sqlalchemy import CursorResult, select, update
from sqlalchemy.exc import IntegrityError
from flask_jwt_extended import (
    create_access_token,
    create_refresh_token,
    current_user,
    jwt_required,
    get_jwt,
    set_refresh_cookies,
    unset_refresh_cookies,
    get_csrf_token,
    decode_token
)
from jwt.exceptions import PyJWTError
from flask_jwt_extended.exceptions import JWTExtendedException

from flask_limiter import RouteLimit
from flask_limiter.util import get_remote_address

from app import db, limiter
from app.auth.emails import (
    PASSWORD_RESET, PASSWORD_RESET_LINK, PASSWORD_RESET_LINK_LIFETIME, REGISTRATION_LINK,
    REGISTRATION_LINK_LIFETIME, send_password_changed_email, send_password_reset_email,
    send_registration_email)
from app.auth.errors import token_revoked
from app.auth.models import TERMS_VERSION, User
from app.auth.schemas import (
    LoginRequest, PasswordResetCompleteRequest, PasswordResetRequest, RegisterCompleteRequest,
    RegisterCompleteResponse, RegisterRequest, TokensResponse, is_guessable,
    is_normalized_email, normalize_email)
from app.utils.breached import is_breached
from app.utils.devices import device_name
from app.utils.errors import ErrorResponse, error_response, service_unavailable
from app.utils.jobs import JobQueueUnavailable, job
from app.utils.links import LinkClaims, LinkExpired, LinkInvalid, read_link_token
from app.utils.log import security_event
from app.utils.passwords import DUMMY_PASSWORD_HASH, hash_password, verify_password
from app.utils.redis_service import get_redis_service
from app.utils.schemas import MessageResponse


auth_bp = Blueprint('auth', __name__, url_prefix='/api/auth')

# Sends sign-up's email from the worker, so the form's answer never waits on
# the mail server, and takes as long for a registered address as a new one
registration_email = job(auth_bp)(send_registration_email)
password_reset_email = job(auth_bp)(send_password_reset_email)
password_changed_email = job(auth_bp)(send_password_changed_email)


def _email_digest(email: str) -> str:
    """Names one account without holding its address.

    Lowercased like MySQL's case-insensitive match on users.email, and hashed
    with SECRET_KEY: a plain hash would let anyone who reads Redis or the log
    confirm a guessed address.
    """
    secret = current_app.config['JWT_SECRET_KEY'].encode()
    return hmac.new(secret, email.lower().encode(), hashlib.sha256).hexdigest()


def _request_email_key() -> str:
    """Rate-limit key for the account the request body's email names,
    whatever the IP: the one being logged in to, or signed up.

    A per-IP limit alone either locks out everyone behind a shared address or,
    set loosely, lets one attacker guess an account's password (or flood an
    inbox) from many. The email is normalized as the schema stores it, so
    every spelling of one address shares a bucket.
    """
    body = request.get_json(silent=True)
    email = body.get('email') if isinstance(body, dict) else None
    if not isinstance(email, str):
        email = ''
    try:
        email = normalize_email(email)
    except ValueError:
        # The request itself will answer 422; any key will do
        email = email.strip()
    return account_key(email)


def account_key(email: str) -> str:
    """Rate-limit key for one account, named by its email"""
    return 'email:' + _email_digest(email)


def account_password_limit(
        key_func: Callable[[], str], deduct_when: Callable[[Response], bool]) -> RouteLimit:
    """Wrong passwords for one account, wherever they are typed: login and
    account deletion share one budget, so guesses spread over both add up.

    key_func names the account with account_key; deduct_when tells a wrong
    password from any other answer.
    """
    return limiter.shared_limit(
        '100 per hour', scope='account-password', key_func=key_func, deduct_when=deduct_when)


# Emails to one address, whichever form asks for them: sign-up's and a
# password reset's share 3 an hour and 6 a day, so no one can flood an inbox
# through the app, alternating the two or not. The 429 tells nothing: it
# comes as soon for an address with an account as for one without.
emails_to_address_limit = limiter.shared_limit(
    '3 per hour;6 per day', scope='emails-to-address', key_func=_request_email_key)


def _login_email_and_ip_key() -> str:
    """The account and the client's address: a lockout hits only that address"""
    return f'{_request_email_key()}:ip:{get_remote_address()}'


def _login_failed(response: Response) -> bool:
    """Only wrong passwords count toward the account limits, so the owner's
    own successful logins never use them up."""
    return response.status_code == 401


def token_user_id(token: str | None, kind: str) -> str | None:
    """The user a valid token of this kind ('access' or 'refresh') belongs
    to, or None.

    A per-user rate limit is checked before @jwt_required runs, so its key
    decodes the token itself; decode_token checks the signature and expiry.
    """
    if token is None:
        return None
    try:
        claims = decode_token(token)
    except (PyJWTError, JWTExtendedException):
        return None
    user_id: str | None = claims.get('sub') if claims.get('type') == kind else None
    return user_id


def _refresh_user_id() -> str | None:
    """The user a valid refresh cookie belongs to, or None"""
    if 'refresh_user_id' not in g:
        g.refresh_user_id = token_user_id(
            request.cookies.get(current_app.config['JWT_REFRESH_COOKIE_NAME']), 'refresh')
    user_id: str | None = g.refresh_user_id
    return user_id


def issue_tokens(user_id: int, auth_time: int, rotating: tuple[str, str] | None = None,
                  email: str | None = None) -> ResponseReturnValue:
    """Build a 200 response carrying a fresh access token and refresh cookie.

    `auth_time` is when the user logged in, carried through every rotation.
    The refresh token expires SESSION_IDLE_TIMEOUT from now, so a session
    left unused that long ends, but never later than JWT_REFRESH_TOKEN_EXPIRES
    after auth_time, however often it is refreshed: a session (or a stolen
    cookie) has an absolute lifetime. Once either passes, the cookie is
    expired and refresh answers 401.

    Each sign-in starts a session, named by a random id (`sid`) that every
    rotation carries on, and that the access token carries too, so the
    account page can tell this device's session from the others. The new
    refresh token's JTI is recorded in Redis as its session's current one;
    `rotating`, when refreshing, is the session's id and the JTI it replaces.
    The blocklist loader treats any refresh token that is not its session's
    current one as revoked. A new session is named by its device
    (app/utils/devices.py).

    `email`, given by sign-up, is answered beside the tokens, so the page
    signs in under the account's address.
    """
    now = datetime.now(timezone.utc)
    session_ends = (datetime.fromtimestamp(auth_time, timezone.utc)
                    + current_app.config['JWT_REFRESH_TOKEN_EXPIRES'])
    lifetime = min(current_app.config['SESSION_IDLE_TIMEOUT'], session_ends - now)
    session_id = rotating[0] if rotating else secrets.token_urlsafe(16)
    access_token = create_access_token(identity=str(user_id), additional_claims={'sid': session_id})
    refresh_token = create_refresh_token(
        identity=str(user_id),
        additional_claims={'auth_time': auth_time, 'sid': session_id},
        expires_delta=lifetime)

    redis_service = get_redis_service()
    jti = decode_token(refresh_token)['jti']
    ttl = max(int(lifetime.total_seconds()), 1)
    if redis_service is None:
        recorded = None
    elif rotating:
        recorded = redis_service.rotate_refresh_token(
            user_id, session_id, rotating[1], jti, ttl_seconds=ttl)
    else:
        recorded = redis_service.store_refresh_token(
            user_id, session_id, jti, ttl_seconds=ttl,
            device=device_name(request.headers.get('User-Agent')))

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
    tokens = (TokensResponse(access_token=access_token) if email is None
              else RegisterCompleteResponse(access_token=access_token, email=email))
    if current_app.config['JWT_COOKIE_CSRF_PROTECT']:
        tokens.refresh_csrf = get_csrf_token(refresh_token)

    response = make_response(jsonify(tokens.model_dump(exclude_none=True)), 200)
    set_refresh_cookies(response, refresh_token)
    return response


def _already_registered() -> ErrorResponse:
    return error_response(
        code='EMAIL_ALREADY_REGISTERED',
        message='Email already registered',
        status=409
    )


def _terms_outdated() -> ErrorResponse:
    return error_response(
        code='TERMS_OUTDATED',
        message='The terms have changed since this page was loaded. Reload the page to read and accept them.',
        status=409
    )


def read_email_link(purpose: str, token: str, lifetime: timedelta) -> LinkClaims | ErrorResponse:
    """What an emailed link of this purpose names, or the answer refusing it"""
    try:
        claims = read_link_token(purpose, token, lifetime)
    except LinkExpired:
        return link_refused(purpose, 'expired')
    except LinkInvalid:
        return link_refused(purpose, 'invalid')
    # Signed by this app, but naming what the form would refuse
    if not is_normalized_email(claims.email):
        return link_refused(purpose, 'invalid')
    return claims


def password_guessable() -> ErrorResponse:
    return error_response(
        code='PASSWORD_GUESSABLE',
        message="Choose a password that doesn't contain your email address or the app's name.",
        status=422)


def password_breached() -> ErrorResponse:
    return error_response(
        code='PASSWORD_BREACHED',
        message='This password has appeared in a data breach. Choose another.',
        status=422)


def link_refused(purpose: str, reason: str) -> ErrorResponse:
    """Refuse an emailed link, and log why: a run of them from one address
    is someone probing the link's format or replaying stolen links"""
    security_event('link_refused', purpose=purpose, reason=reason)
    if reason == 'registered':
        return _already_registered()
    if reason == 'expired':
        return error_response(code='LINK_EXPIRED', message='This link has expired', status=400)
    if reason == 'used':
        return error_response(
            code='LINK_USED', message='This link has already been used', status=400)
    return error_response(code='LINK_INVALID', message='This link is not valid', status=400)


@auth_bp.route('/register', methods=['POST'])
@limiter.limit('10 per hour')
@emails_to_address_limit
def register() -> ResponseReturnValue:
    """Sign-up's first step: email the address a link to finish.

    The same answer, as fast, whether the address has an account or not;
    the worker decides which email to send (auth/emails.py). Nothing is
    stored until the link is used, so a mistyped address leaves nothing.
    """
    payload = RegisterRequest.model_validate(request.get_json())
    registration_email.send(payload.email)
    security_event('registration_requested', account=_email_digest(payload.email))
    return jsonify(MessageResponse(message='Check your inbox').model_dump()), 202


@auth_bp.route('/register/complete', methods=['POST'])
@limiter.limit('10 per hour')
def complete_registration() -> ResponseReturnValue:
    """Sign-up's second step: the emailed link's token, which proves the
    address, and the password. Creates the account and logs in."""
    payload = RegisterCompleteRequest.model_validate(request.get_json())

    # A page loaded before the terms changed showed the old ones, which the
    # user can no longer accept
    if payload.terms_version != TERMS_VERSION:
        return _terms_outdated()

    claims = read_email_link(REGISTRATION_LINK, payload.token, REGISTRATION_LINK_LIFETIME)
    if not isinstance(claims, LinkClaims):
        return claims
    email = claims.email

    # A link used twice: the first made the account. A fast path that skips
    # hashing the password; the unique index on users.email is the real
    # check, below.
    stmt = select(User).where(User.email == email)
    if db.session.execute(stmt).scalar_one_or_none():
        return link_refused(REGISTRATION_LINK, 'registered')

    # Before the link is spent, so the user can try another password with it
    if is_guessable(payload.password, email, current_app.config['APP_NAME']):
        return password_guessable()

    # A link works once, even after the account it made is deleted
    redis_service = get_redis_service()
    claimed = redis_service.claim_link(
        payload.token, int(REGISTRATION_LINK_LIFETIME.total_seconds())) if redis_service else None
    if claimed is None:
        return service_unavailable()
    if not claimed:
        return link_refused(REGISTRATION_LINK, 'used')
    assert redis_service is not None

    try:
        # Nothing to keep yet: end the read above, so no pooled database
        # connection waits on a third party
        db.session.rollback()
        # Last, so a request refused anyway never reaches the third party
        if is_breached(payload.password):
            redis_service.release_link(payload.token)
            return password_breached()

        user = User(email=email, terms_version=payload.terms_version)
        user.set_password(payload.password)
        db.session.add(user)
        db.session.commit()
    except IntegrityError:
        # Another request registered the same email since the check above
        # (a double submit, or a client retrying)
        db.session.rollback()
        return link_refused(REGISTRATION_LINK, 'registered')
    except BaseException:
        # Not used after all (the database or the password hashing failed):
        # the link must still work
        redis_service.release_link(payload.token)
        raise

    security_event('registered', user_id=user.id)
    return issue_tokens(
        user.id, auth_time=int(datetime.now(timezone.utc).timestamp()), email=email)


@auth_bp.route('/password-reset', methods=['POST'])
@limiter.limit('10 per hour')
@emails_to_address_limit
def request_password_reset() -> ResponseReturnValue:
    """A password reset's first step: email the account a link to choose a
    new password.

    The same answer, as fast, whether the address has an account or not;
    the worker emails only an address that has one (auth/emails.py).
    """
    payload = PasswordResetRequest.model_validate(request.get_json())
    password_reset_email.send(payload.email)
    security_event('password_reset_requested', account=_email_digest(payload.email))
    return jsonify(MessageResponse(message='Check your inbox').model_dump()), 202


@auth_bp.route('/password-reset/complete', methods=['POST'])
@limiter.limit('10 per hour')
def complete_password_reset() -> ResponseReturnValue:
    """A password reset's second step: the emailed link's token, which proves
    the address, and the new password. Ends every session of the account;
    the user then logs in with the new password.

    The link works while the password it was sent for is the account's (its
    password_state), so once: the reset changes it.
    """
    payload = PasswordResetCompleteRequest.model_validate(request.get_json())

    claims = read_email_link(PASSWORD_RESET_LINK, payload.token, PASSWORD_RESET_LINK_LIFETIME)
    if not isinstance(claims, LinkClaims):
        return claims
    user = db.session.execute(
        select(User).where(User.email == claims.email)).scalar_one_or_none()
    # The account was deleted since the link was sent
    if user is None:
        return link_refused(PASSWORD_RESET_LINK, 'invalid')
    if not hmac.compare_digest(user.password_state, claims.state):
        return link_refused(PASSWORD_RESET_LINK, 'used')

    if is_guessable(payload.password, user.email, current_app.config['APP_NAME']):
        return password_guessable()

    user_id, email, old_hash = user.id, user.email, user.password_hash
    # Nothing to keep yet: end the read above, so no pooled database
    # connection waits on a third party or on hashing
    db.session.rollback()
    # Last, so a request refused anyway never reaches the third party
    if is_breached(payload.password):
        return password_breached()
    # Before the sessions end, so the moment between that and the new
    # password is short: a login with the old one there would outlive it
    new_hash = hash_password(payload.password)

    # First, as deleting the account does: a reset is how an owner locks
    # out whoever has the password, so it changes nothing unless Redis can
    # end their sessions
    redis_service = get_redis_service()
    sessions = redis_service.revoke_all_user_tokens(user_id) if redis_service else None
    if sessions is None:
        return service_unavailable()

    # Only if the password is still the one the link was sent for: of two
    # requests racing with one link, the second changes nothing
    changed = cast('CursorResult[Any]', db.session.execute(
        update(User)
        .where(User.id == user_id, User.password_hash == old_hash)
        .values(password_hash=new_hash)))
    db.session.commit()
    if changed.rowcount == 0:
        return link_refused(PASSWORD_RESET_LINK, 'used')

    security_event('password_reset', user_id=user_id, sessions=sessions)
    try:
        password_changed_email.send(email, PASSWORD_RESET)
    except JobQueueUnavailable:
        # The password is changed: say so, rather than a 503 that would
        # send the user back to a link that no longer works
        current_app.logger.exception('Could not queue the password changed email')

    response = make_response(
        jsonify(MessageResponse(message='Password changed').model_dump()), 200)
    # This browser's session ended with the others
    unset_refresh_cookies(response)
    return response


@auth_bp.route('/login', methods=['POST'])
# Loose per IP, so a shared address keeps working.
# Tight per account and address, so a stranger's wrong guesses lock out only
# the stranger; loose per account alone, which bounds guessing spread over
# many addresses.
@limiter.limit('20 per minute')
@limiter.limit('5 per minute', key_func=_login_email_and_ip_key, deduct_when=_login_failed)
@account_password_limit(key_func=_request_email_key, deduct_when=_login_failed)
def login() -> ResponseReturnValue:
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
    return issue_tokens(user.id, auth_time=int(datetime.now(timezone.utc).timestamp()))


@auth_bp.route('/refresh', methods=['POST'])
# Per user, not per IP: everyone behind a shared address refreshes from it,
# and a 429 here would log them all out. A request without a valid cookie
# is exempt, since @jwt_required turns it away cheaply with a 401.
@limiter.limit(
    '10 per minute',
    key_func=lambda: f'user:{_refresh_user_id()}',
    exempt_when=lambda: _refresh_user_id() is None)
@jwt_required(refresh=True, locations=['cookies'])
def refresh() -> ResponseReturnValue:
    """Rotate: issue a new token pair and revoke the refresh token just used"""
    claims = get_jwt()
    return issue_tokens(current_user.id, auth_time=claims['auth_time'],
                        rotating=(claims['sid'], claims['jti']))


@auth_bp.route('/logout', methods=['POST'])
@jwt_required(refresh=True, locations=['cookies'])
def logout() -> ResponseReturnValue:
    user_id = current_user.id
    # The blocklist loader already refused a refresh token without a session
    session_id = get_jwt()['sid']

    redis_service = get_redis_service()
    if redis_service:
        redis_service.revoke_token(user_id, session_id)
    security_event('logout', user_id=user_id)

    response = make_response(jsonify(MessageResponse(message='Logged out').model_dump()), 200)
    unset_refresh_cookies(response)
    return response


@auth_bp.route('/clear-cookies', methods=['POST'])
def clear_cookies() -> ResponseReturnValue:
    """Expire the refresh cookies when a logout request itself failed.

    They are HttpOnly, so the client cannot remove them. No token is needed,
    since logout may have failed on exactly that. Requiring a JSON body means
    another site can only send this with a CORS preflight, which it won't pass.
    """
    if not request.is_json:
        abort(415)

    response = make_response(jsonify(MessageResponse(message='Cookies cleared').model_dump()), 200)
    unset_refresh_cookies(response)
    return response


@auth_bp.route('/logout-all', methods=['POST'])
@jwt_required(refresh=True, locations=['cookies'])
def logout_all() -> ResponseReturnValue:
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
    response = make_response(jsonify(MessageResponse(message=message).model_dump()), 200)
    unset_refresh_cookies(response)
    return response
