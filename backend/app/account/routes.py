import hmac
import re
import secrets
from datetime import datetime, timezone
from typing import Any, cast

from flask import Blueprint, Response, abort, current_app, jsonify, make_response, request
from flask.typing import ResponseReturnValue
from flask_jwt_extended import current_user, get_jwt, jwt_required, unset_refresh_cookies
from sqlalchemy import CursorResult, delete, select, update
from sqlalchemy.exc import IntegrityError

from app import db, limiter
from app.account.emails import (
    EMAIL_CHANGE_LINK, EMAIL_CHANGE_LINK_LIFETIME, EMAIL_UNDO_LINK, EMAIL_UNDO_LINK_LIFETIME,
    change_state, send_email_change_email, send_email_changed_email, state_account, undo_state)
from app.account.schemas import (
    AccountDeleteRequest, AccountExport, AccountResponse, DataExportResponse, EmailChangeRequest,
    EmailChangedResponse, EmailLinkRequest, PasswordChangeRequest, SessionResponse, SessionsResponse,
)
from app.auth.models import User
from app.auth.emails import PASSWORD_CHANGE
from app.auth.routes import (
    account_key, account_password_limit, emails_to_address_limit, issue_tokens, link_refused,
    password_breached, password_changed_email, password_guessable, read_email_link)
from app.auth.schemas import is_guessable
from app.utils.breached import is_breached
from app.utils.passwords import hash_password
from app.utils.jobs import JobQueueUnavailable, job
from app.utils.links import LinkClaims
from app.utils.errors import error_response, service_unavailable
from app.utils.exports import export_user_data
from app.utils.log import security_event
from app.utils.redis_service import get_redis_service
from app.utils.schemas import MessageResponse

account_bp = Blueprint('account', __name__, url_prefix='/api/account')

# Sent from the worker, so a request never waits on the mail server
email_change_email = job(account_bp)(send_email_change_email)
email_changed_email = job(account_bp)(send_email_changed_email)


@account_bp.route('', methods=['GET'])
@jwt_required()
def get_account() -> ResponseReturnValue:
    """The signed-in user's account. Every app keeps it, so shared tests use
    it as their protected route; account settings belong here."""
    return jsonify(AccountResponse.model_validate(current_user).model_dump()), 200


@account_bp.route('/export', methods=['GET'])
@jwt_required()
# Per user: an export reads every row the user owns, so it costs more than
# any other read. A key function must not touch the database (see below).
@limiter.limit('10 per hour', key_func=lambda: f'export:user:{current_user.id}')
def export_account() -> ResponseReturnValue:
    """Everything the app keeps on the signed-in user, as one JSON document
    (GDPR Art. 15 and 20). No password is asked for: a session can already
    read all of it through the other routes."""
    body = DataExportResponse(
        exported_at=datetime.now(timezone.utc),
        account=AccountExport.model_validate(current_user),
        data=export_user_data(current_user.id),
    )
    security_event('data_exported', user_id=current_user.id)
    return jsonify(body.model_dump()), 200


def _wrong_password(response: Response) -> bool:
    return response.status_code == 403


@account_bp.route('/delete', methods=['POST'])
# The token first: the limits below run only for a signed-in user, so their
# keys read current_user, which the user loader has already fetched. A key
# function must not touch the database: Flask-Limiter takes any error it
# raises for a Redis outage and retries, for as long as MySQL stays down.
@jwt_required()
# Per user, so an access token alone is not enough to guess the password
# behind it. Only wrong passwords count.
@limiter.limit(
    '5 per minute',
    key_func=lambda: f'delete-account:user:{current_user.id}',
    deduct_when=_wrong_password)
# Keyed as login keys the account, so the two share a budget of wrong passwords
@account_password_limit(
    key_func=lambda: account_key(current_user.email), deduct_when=_wrong_password)
def delete_account() -> ResponseReturnValue:
    """Delete the signed-in user's account and everything it owns.

    POST, not DELETE: a body on DELETE has no defined meaning (RFC 9110), and
    some proxies drop it. The password is asked for again, so a session left
    open, or a stolen access token, cannot delete the account. Its 403 is not
    a 401, which the client would take for a session that has ended.
    """
    payload = AccountDeleteRequest.model_validate(request.get_json())
    if not current_user.check_password(payload.password):
        security_event('wrong_password', user_id=current_user.id)
        return error_response(
            code='WRONG_PASSWORD',
            message='The password is incorrect',
            status=403
        )

    # Sessions first: if Redis cannot revoke them, nothing is deleted yet and
    # the user can try again. A token issued after this (a refresh racing
    # the delete) is refused anyway, since its user no longer exists.
    user_id = current_user.id
    redis_service = get_redis_service()
    revoked = redis_service.revoke_all_user_tokens(user_id) if redis_service else None
    if revoked is None:
        return service_unavailable('Could not delete the account, please try again shortly')

    # One statement: every table a feature keeps per user references users.id
    # with ON DELETE CASCADE (tests/unit/test_foreign_keys.py), so the
    # database deletes those rows without the ORM loading them
    db.session.execute(delete(User).where(User.id == user_id))
    db.session.commit()

    security_event('account_deleted', user_id=user_id)
    response = make_response(jsonify(MessageResponse(message='Account deleted').model_dump()), 200)
    unset_refresh_cookies(response)
    return response


def _email_taken() -> ResponseReturnValue:
    return error_response(
        code='EMAIL_ALREADY_REGISTERED', message='Email already registered', status=409)


@account_bp.route('/email', methods=['POST'])
# The token first, as deletion's: the limits below key on current_user
@jwt_required()
@limiter.limit('10 per hour', key_func=lambda: f'email-change:user:{current_user.id}')
@limiter.limit(
    '5 per minute',
    key_func=lambda: f'email-change-password:user:{current_user.id}',
    deduct_when=_wrong_password)
@account_password_limit(
    key_func=lambda: account_key(current_user.email), deduct_when=_wrong_password)
# The new address's inbox, in the budget sign-up and a reset share
@emails_to_address_limit
def request_email_change() -> ResponseReturnValue:
    """An email change's first step: email the new address a link that
    moves the account there.

    The password is asked for again: a session alone must not move the
    account to another inbox, from which a reset would take it. The answer
    is the same whether the new address has an account or not; the worker
    tells its inbox which (account/emails.py).
    """
    payload = EmailChangeRequest.model_validate(request.get_json())
    if not current_user.check_password(payload.password):
        security_event('wrong_password', user_id=current_user.id)
        return error_response(code='WRONG_PASSWORD', message='The password is incorrect', status=403)
    # Case aside, as MySQL matches users.email: the same address
    if payload.email.lower() == current_user.email.lower():
        return error_response(
            code='EMAIL_UNCHANGED', message='This is already your email address', status=422)

    email_change_email.send(current_user.id, payload.email)
    security_event('email_change_requested', user_id=current_user.id)
    return jsonify(MessageResponse(message='Check your inbox').model_dump()), 202


@account_bp.route('/email/complete', methods=['POST'])
# No session: the link may be opened on another device
@limiter.limit('10 per hour')
def complete_email_change() -> ResponseReturnValue:
    """An email change's second step: the link to the new address, which
    proves it, moves the account there. Sessions stay: tokens name the
    account by id. The old address is told, with a link back."""
    payload = EmailLinkRequest.model_validate(request.get_json())
    claims = read_email_link(EMAIL_CHANGE_LINK, payload.token, EMAIL_CHANGE_LINK_LIFETIME)
    if not isinstance(claims, LinkClaims):
        return claims
    user = state_account(claims.state)
    if user is None:
        return link_refused(EMAIL_CHANGE_LINK, 'invalid')
    # The address or the password changed since the link was sent (this
    # link used already, or an owner taking the account back)
    if not hmac.compare_digest(change_state(user), claims.state):
        return link_refused(EMAIL_CHANGE_LINK, 'used')
    if db.session.execute(select(User.id).where(User.email == claims.email)).first():
        return _email_taken()

    user_id, old_email = user.id, user.email
    user.email = claims.email
    try:
        db.session.commit()
    except IntegrityError:
        # Someone signed up with the address since the check above
        db.session.rollback()
        return _email_taken()

    security_event('email_changed', user_id=user_id)
    try:
        email_changed_email.send(user_id, old_email)
    except JobQueueUnavailable:
        # The address has changed: say so, rather than a 503 that would
        # send the user back to a link that no longer works
        current_app.logger.exception('Could not queue the email changed email')
    return jsonify(EmailChangedResponse(email=claims.email).model_dump()), 200


@account_bp.route('/email/undo', methods=['POST'])
@limiter.limit('10 per hour')
def undo_email_change() -> ResponseReturnValue:
    """Move the account back to the address the link was sent to, end
    every session, and replace the password with one nobody knows: its
    owner did not make the change, and whoever did may know the password.
    That also ends the change's own link, and every other pending link,
    since each names the password. The owner then resets the password,
    which reaches them at this address again."""
    payload = EmailLinkRequest.model_validate(request.get_json())
    claims = read_email_link(EMAIL_UNDO_LINK, payload.token, EMAIL_UNDO_LINK_LIFETIME)
    if not isinstance(claims, LinkClaims):
        return claims
    user = state_account(claims.state)
    if user is None or not hmac.compare_digest(undo_state(user), claims.state):
        return link_refused(EMAIL_UNDO_LINK, 'invalid')
    if user.email == claims.email:
        return link_refused(EMAIL_UNDO_LINK, 'used')
    if db.session.execute(select(User.id).where(User.email == claims.email)).first():
        return _email_taken()

    # First, as a reset does: whoever moved the account must lose it, so
    # nothing changes unless Redis can end their sessions
    user_id = user.id
    redis_service = get_redis_service()
    sessions = redis_service.revoke_all_user_tokens(user_id) if redis_service else None
    if sessions is None:
        return service_unavailable()

    user.email = claims.email
    # Without it, the address is back where the change's own link expects
    # it, and that link would move the account away again
    user.set_password(secrets.token_urlsafe(32))
    try:
        db.session.commit()
    except IntegrityError:
        db.session.rollback()
        return _email_taken()

    security_event('email_change_undone', user_id=user_id, sessions=sessions)
    response = make_response(
        jsonify(EmailChangedResponse(email=claims.email).model_dump()), 200)
    unset_refresh_cookies(response)
    return response


@account_bp.route('/password', methods=['POST'])
# The token first, as deletion's: the limits below key on current_user
@jwt_required()
# Each new password may reach the breach check's third party
@limiter.limit('10 per hour', key_func=lambda: f'password-change:user:{current_user.id}')
@limiter.limit(
    '5 per minute',
    key_func=lambda: f'password-change-password:user:{current_user.id}',
    deduct_when=_wrong_password)
@account_password_limit(
    key_func=lambda: account_key(current_user.email), deduct_when=_wrong_password)
def change_password() -> ResponseReturnValue:
    """Replace the signed-in account's password, given the current one.

    Every token was issued under the old password (add_account_claims), so
    every device is logged out, this one included: it gets a new login in
    the answer, as login gives one. The account is emailed (ASVS 6.3.7).
    """
    payload = PasswordChangeRequest.model_validate(request.get_json())
    if not current_user.check_password(payload.current_password):
        security_event('wrong_password', user_id=current_user.id)
        return error_response(code='WRONG_PASSWORD', message='The password is incorrect', status=403)
    # Both NFKC-normalized by Password, so any spelling of the same one
    if payload.new_password == payload.current_password:
        return error_response(
            code='PASSWORD_UNCHANGED',
            message='Choose a password different from your current one.',
            status=422)
    if is_guessable(payload.new_password, current_user.email, current_app.config['APP_NAME']):
        return password_guessable()

    user_id, email, old_hash = current_user.id, current_user.email, current_user.password_hash
    # Nothing to keep yet: end the read, so no pooled database connection
    # waits on a third party or on hashing
    db.session.rollback()
    # Last, so a request refused anyway never reaches the third party
    if is_breached(payload.new_password):
        return password_breached()
    # Before the sessions end, so the moment between that and the new
    # password is short
    new_hash = hash_password(payload.new_password)

    # As a reset: changing nothing unless Redis can end the other sessions.
    # Their access tokens stop at once anyway (add_account_claims); this
    # ends their refresh tokens too.
    redis_service = get_redis_service()
    sessions = redis_service.revoke_all_user_tokens(user_id) if redis_service else None
    if sessions is None:
        return service_unavailable()

    # Only if the password is still the one checked above: of two changes
    # racing, the second changes nothing
    changed = cast('CursorResult[Any]', db.session.execute(
        update(User)
        .where(User.id == user_id, User.password_hash == old_hash)
        .values(password_hash=new_hash)))
    db.session.commit()
    if changed.rowcount == 0:
        return error_response(code='WRONG_PASSWORD', message='The password is incorrect', status=403)

    security_event('password_changed', user_id=user_id, sessions=sessions)
    try:
        password_changed_email.send(email, PASSWORD_CHANGE)
    except JobQueueUnavailable:
        # The password has changed: answer the new login regardless
        current_app.logger.exception('Could not queue the password changed email')
    # A fresh login: the password was just typed. Should Redis fail here,
    # the answer is a 503 and this device logs in again, with the new one.
    return issue_tokens(user_id, auth_time=int(datetime.now(timezone.utc).timestamp()))


# What a session id can look like (secrets.token_urlsafe in auth/routes.py):
# anything else names no session
_SESSION_ID = re.compile(r'[A-Za-z0-9_-]{1,64}')


def _utc(timestamp: int) -> datetime:
    return datetime.fromtimestamp(timestamp, timezone.utc)


@account_bp.route('/sessions', methods=['GET'])
@jwt_required()
def list_sessions() -> ResponseReturnValue:
    """The account's live sessions, so the user can see where it is signed
    in and end any of them (ASVS 7.5.2). Each is named by its device and
    dated; the one this request's token belongs to is marked current."""
    redis_service = get_redis_service()
    sessions = redis_service.list_sessions(current_user.id) if redis_service else None
    if sessions is None:
        return service_unavailable()
    current = get_jwt().get('sid')
    body = SessionsResponse(sessions=[
        SessionResponse(
            id=session['id'], device=session['device'],
            signed_in_at=_utc(session['signed_in_at']),
            last_active_at=_utc(session['last_active_at']),
            current=session['id'] == current)
        for session in sessions])
    return jsonify(body.model_dump()), 200


@account_bp.route('/sessions/<session_id>', methods=['DELETE'])
@jwt_required()
def revoke_session(session_id: str) -> ResponseReturnValue:
    """End one of the account's sessions: that device is refused at its
    next request (the user loader checks its session, DECISIONS.md). A
    session another account has, or none has, is a 404 alike."""
    if not _SESSION_ID.fullmatch(session_id):
        abort(404)
    redis_service = get_redis_service()
    ended = redis_service.revoke_session(current_user.id, session_id) if redis_service else None
    if ended is None:
        return service_unavailable('Could not log out that device, please try again shortly')
    if not ended:
        abort(404)
    security_event('session_revoked', user_id=current_user.id)
    return jsonify(MessageResponse(message='Logged out').model_dump()), 200
