"""The answers both features give: the factory's JWT loaders, the auth
routes and the account routes build them here, so each says one thing."""
from app.utils.errors import ErrorResponse, error_response
from app.utils.log import security_event


# A refresh token that was rotated, logged out or revoked, whether the
# blocklist caught it or a racing refresh rotated it first
def token_revoked() -> ErrorResponse:
    return error_response(code='AUTH_TOKEN_REVOKED', message='Session revoked', status=401)


# A token the client should never have had, or one whose account is gone:
# the frontend signs the user out on either
def token_invalid() -> ErrorResponse:
    return error_response(code='AUTH_INVALID_TOKEN', message='Invalid authentication token', status=401)


# A password typed again to confirm an account change, and wrong: a 403, not
# a 401, which the client would take for a session that has ended
def wrong_password() -> ErrorResponse:
    return error_response(code='WRONG_PASSWORD', message='The password is incorrect', status=403)


def already_registered() -> ErrorResponse:
    return error_response(code='EMAIL_ALREADY_REGISTERED', message='Email already registered', status=409)


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
        return already_registered()
    if reason == 'expired':
        return error_response(code='LINK_EXPIRED', message='This link has expired', status=400)
    if reason == 'used':
        return error_response(
            code='LINK_USED', message='This link has already been used', status=400)
    return error_response(code='LINK_INVALID', message='This link is not valid', status=400)
