from app.utils.errors import ErrorResponse, error_response


# A refresh token that was rotated, logged out or revoked, whether the
# blocklist caught it or a racing refresh rotated it first
def token_revoked() -> ErrorResponse:
    return error_response(code='AUTH_TOKEN_REVOKED', message='Session revoked', status=401)


# A token the client should never have had, or one whose account is gone:
# the frontend signs the user out on either
def token_invalid() -> ErrorResponse:
    return error_response(code='AUTH_INVALID_TOKEN', message='Invalid authentication token', status=401)
