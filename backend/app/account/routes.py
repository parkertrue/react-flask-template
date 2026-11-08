from datetime import datetime, timezone

from flask import Blueprint, Response, jsonify, make_response, request
from flask.typing import ResponseReturnValue
from flask_jwt_extended import current_user, jwt_required, unset_refresh_cookies
from sqlalchemy import delete

from app import db, limiter
from app.account.schemas import (
    AccountDeleteRequest, AccountExport, AccountResponse, DataExportResponse,
)
from app.auth.models import User
from app.auth.routes import account_key, account_password_limit
from app.utils.errors import error_response, service_unavailable
from app.utils.exports import export_user_data
from app.utils.log import security_event
from app.utils.redis_service import get_redis_service
from app.utils.schemas import MessageResponse

account_bp = Blueprint('account', __name__, url_prefix='/api/account')


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
