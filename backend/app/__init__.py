from flask import Flask, request
from flask_sqlalchemy import SQLAlchemy
from flask_migrate import Migrate
from flask_jwt_extended import JWTManager
from flask_jwt_extended.exceptions import CSRFError
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from pydantic import ValidationError
from sqlalchemy.exc import InterfaceError, OperationalError
from werkzeug.exceptions import HTTPException
from werkzeug.middleware.proxy_fix import ProxyFix

from app.auth.errors import token_invalid, token_revoked
from app.config import get_config
from app.utils.errors import error_response, service_unavailable
from app.utils.log import configure_logging, security_event
from app.utils.passwords import PasswordHashingBusy, init_password_hashing
from app.utils.redis_service import (
    TokenStoreUnavailable, connect_redis, get_redis_service)


jwt = JWTManager()
db = SQLAlchemy()
migrate = Migrate()
# No default limits: only the routes that need one declare it. nginx caps
# every client's request rate, and a per-IP daily quota on the whole API
# would lock out everyone sharing an address (an office, a campus, a mobile
# carrier's NAT) once a few of them hit it.
limiter = Limiter(key_func=get_remote_address)

# The code and message for each HTTP error the API expects; any other status
# a route aborts with gets HTTP_ERROR and Werkzeug's name for it.
HTTP_ERRORS = {
    400: dict(code='BAD_REQUEST', message='Malformed request'),
    404: dict(code='NOT_FOUND', message='Resource not found'),
    405: dict(code='METHOD_NOT_ALLOWED', message='Method not allowed'),
    413: dict(code='PAYLOAD_TOO_LARGE', message='Request body too large'),
    415: dict(code='UNSUPPORTED_MEDIA_TYPE', message='Request body must be JSON'),
    429: dict(
        code='RATE_LIMITED', message='Too many requests, please try again later'),
    500: dict(code='INTERNAL_ERROR', message='Something went wrong'),
}


def create_app():
    """Build the app with the config APP_ENV selects (config.get_config)"""
    app = Flask(__name__)
    configure_logging(app)

    config = get_config()
    app.config.from_object(config)

    # Behind nginx, REMOTE_ADDR is the proxy's address. Without this every
    # client shares one rate-limit bucket, so a single user can lock everyone
    # out of login. Only trust as many X-Forwarded-* hops as there are proxies.
    proxies = app.config['TRUSTED_PROXY_COUNT']
    if proxies:
        app.wsgi_app = ProxyFix(
            app.wsgi_app, x_for=proxies, x_proto=proxies, x_host=proxies)

    jwt.init_app(app)
    db.init_app(app)
    migrate.init_app(app, db)

    # A Redis failure must not stop the app from booting; get_redis_service()
    # retries later, and the blocklist loader below refuses refresh tokens
    # meanwhile.
    app.extensions['redis_service'] = None
    if app.config['USES_SERVICES']:
        connect_redis(app)

    if app.config['RATELIMIT_ENABLED']:
        limiter.init_app(app)

    init_password_hashing(app)

    # Imported here for the same reason as the routes below
    from app.auth.models import User

    @jwt.user_lookup_loader
    def load_user(jwt_header, jwt_payload):
        """Runs on every @jwt_required request: the token's user must exist.

        A deleted account's access token stays valid until it expires; this
        turns it away on every route at the cost of one primary-key lookup,
        rather than each route remembering to check. Routes read the user
        as flask_jwt_extended.current_user.
        """
        return db.session.get(User, int(jwt_payload['sub']))

    @jwt.user_lookup_error_loader
    def user_not_found(jwt_header, jwt_payload):
        security_event('token_invalid', reason='User not found',
                       user_id=int(jwt_payload['sub']))
        # Answered as a bad token, so the frontend signs the user out
        return token_invalid()

    @jwt.token_in_blocklist_loader
    def check_if_token_revoked(jwt_header, jwt_payload):
        # Only refresh tokens are tracked in Redis
        if jwt_payload.get('type') != 'refresh':
            return False

        jti = jwt_payload.get('jti')
        user_id = jwt_payload.get('sub')
        if not jti or not user_id:
            return True
        try:
            user_id_int = int(user_id)
        except (ValueError, TypeError):
            return True

        # Fail closed: without Redis we cannot tell a live refresh token from a
        # revoked one, so refuse it rather than honor tokens the user already
        # logged out of. Refuse it as a 503, not a revocation: the client
        # keeps its session and tries again once Redis is back.
        redis_service = get_redis_service()
        is_valid = redis_service.is_token_valid(user_id_int, jti) if redis_service else None
        if is_valid is None:
            raise TokenStoreUnavailable()
        # Not in the allowlist: logged out, rotated, or expired
        return not is_valid

    @jwt.unauthorized_loader
    def missing_token(reason):
        return error_response(
            code='AUTH_MISSING_TOKEN',
            message='Authentication required',
            status=401
        )

    # A forged or malformed token (a bad signature, alg none) or a refresh
    # token sent as an access token: the client never had a token like it.
    # The reason is PyJWT's or flask-jwt-extended's, and never holds the token.
    @jwt.invalid_token_loader
    def invalid_token(reason):
        security_event('token_invalid', reason=reason)
        return token_invalid()

    # A refresh cookie without its CSRF value, or with the wrong one, is how a
    # stolen cookie alone shows up. Answered as flask-jwt-extended's own
    # handler would (a missing token), but logged first.
    @app.errorhandler(CSRFError)
    def csrf_refused(e):
        security_event('token_invalid', reason=str(e))
        return missing_token(str(e))

    @jwt.expired_token_loader
    def expired_token(jwt_header, jwt_payload):
        return error_response(
            code='AUTH_TOKEN_EXPIRED',
            message='Session expired',
            status=401
        )

    @jwt.revoked_token_loader
    def revoked_token(jwt_header, jwt_payload):
        # A refresh token that was rotated, logged out or revoked: a replay
        # of an old one is how a stolen cookie shows up
        sub = jwt_payload['sub']
        security_event('refresh_refused', user_id=int(sub) if sub.isdigit() else sub)
        return token_revoked()

    @app.errorhandler(ValidationError)
    def handle_pydantic_error(e):
        return error_response(
            code='VALIDATION_ERROR',
            message='Invalid input',
            status=422
        )

    @app.errorhandler(TokenStoreUnavailable)
    def token_store_unavailable(e):
        return service_unavailable()

    @app.errorhandler(PasswordHashingBusy)
    def password_hashing_busy(e):
        return service_unavailable('The server is busy, please try again shortly')

    # MySQL stopped, hung (the 15s query timeout), or the connection dropped
    # mid-query: an outage, not a bug, so answer 503 as Redis outages do and
    # the client keeps its session. IntegrityError and the like stay 500s.
    # Flask logs only unhandled exceptions, so log this one here.
    @app.errorhandler(OperationalError)
    @app.errorhandler(InterfaceError)
    def database_unavailable(e):
        app.logger.exception('Database unavailable')
        return service_unavailable()

    # Werkzeug's own error pages are HTML, which the frontend cannot show;
    # every error leaves the API in the same JSON shape. Flask logs an
    # unhandled exception's traceback before this answers it as a 500.
    @app.errorhandler(HTTPException)
    def http_error(e):
        if e.code == 429:
            # Flask-Limiter's description is the limit that was hit
            security_event('rate_limited', path=request.path, limit=e.description)
        return error_response(
            **HTTP_ERRORS.get(
                e.code, dict(code='HTTP_ERROR', message=e.name)),
            status=e.code
        )

    @app.after_request
    def no_store(response):
        """API responses carry tokens and private data: no cache may keep them"""
        response.headers.setdefault('Cache-Control', 'no-store')
        return response

    # Imported here, not at the top: the feature modules import db and
    # limiter from this package, so a module-level import would be circular.
    from app.features import register_features
    register_features(app)

    return app
