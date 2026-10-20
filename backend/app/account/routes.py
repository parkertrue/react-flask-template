from flask import Blueprint, jsonify, make_response, request
from flask_jwt_extended import current_user, jwt_required, unset_jwt_cookies
from sqlalchemy import delete

from app import db, limiter
from app.account.schemas import AccountDeleteRequest, AccountResponse
from app.auth.models import User
from app.auth.routes import account_key, account_password_limit, token_user_id
from app.utils.errors import error_response, service_unavailable
from app.utils.log import security_event
from app.utils.redis_service import get_redis_service

account_bp = Blueprint('account', __name__, url_prefix='/api/account')


@account_bp.route('', methods=['GET'])
@jwt_required()
def get_account():
    """The signed-in user's account. Every app keeps it, so shared tests use
    it as their protected route; account settings belong here."""
    return jsonify(AccountResponse.model_validate(current_user).model_dump()), 200


def _access_user_id():
    """The user a valid access token belongs to, or None"""
    header = request.headers.get('Authorization', '')
    if not header.startswith('Bearer '):
        return None
    return token_user_id(header.removeprefix('Bearer '), 'access')


def _account_key():
    """The account a valid access token belongs to, keyed as login keys it,
    so the two share a budget of wrong passwords"""
    user_id = _access_user_id()
    user = db.session.get(User, int(user_id)) if user_id else None
    # A request without a valid token is turned away with a 401 and never
    # counts, so any key will do
    return account_key(user.email) if user else 'email:none'


def _wrong_password(response):
    return response.status_code == 403


@account_bp.route('/delete', methods=['POST'])
# Per user, so an access token alone is not enough to guess the password
# behind it. Only wrong passwords count, so a request without a valid token,
# which @jwt_required turns away with a 401, never does.
@limiter.limit(
    '5 per minute',
    key_func=lambda: f'delete-account:user:{_access_user_id()}',
    deduct_when=_wrong_password)
@account_password_limit(key_func=_account_key, deduct_when=_wrong_password)
@jwt_required()
def delete_account():
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
    response = make_response(jsonify({'message': 'Account deleted'}), 200)
    unset_jwt_cookies(response)
    return response
