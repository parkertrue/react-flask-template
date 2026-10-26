import time
import redis
from redis.backoff import NoBackoff
from redis.retry import Retry
from flask import Flask, current_app

# How long to wait after a failed connection before trying again. Each attempt
# can block a request for several seconds while Redis is down: the timeouts
# below don't cover looking up the name of a stopped container, which can
# take seconds on its own.
RECONNECT_INTERVAL_SECONDS = 5

# The app's client. redis-py's default retries a failed command 10 times with
# backoff, so every request would hang for ~30s while Redis is down. One
# immediate retry is enough to replace a connection Redis closed; after that,
# fail fast.
REDIS_CLIENT_OPTIONS = {
    'socket_connect_timeout': 2,
    'socket_timeout': 2,
    'retry': Retry(NoBackoff(), 1),
}

# The rate limiter's client (config.py): no retry at all. While Redis is
# down, Flask-Limiter re-checks it on any request, rate-limited or not, so a
# retry would only double that request's wait. A failed call costs nothing:
# the limiter counts in memory until Redis answers again.
RATELIMIT_REDIS_OPTIONS = {**REDIS_CLIENT_OPTIONS, 'retry': Retry(NoBackoff(), 0)}


class TokenStoreUnavailable(Exception):
    """A refresh token could not be checked because Redis is unavailable.

    The token is refused either way; this makes the answer a 503 (try again
    soon) rather than a 401 (signed out), since the token may be fine.
    """


def get_redis_service() -> 'RedisService | None':
    """The current app's RedisService, or None if Redis is disabled or down.

    Looked up per call rather than imported, so every app instance (one per
    gunicorn worker, several per test session) sees its own service.
    """
    service = current_app.extensions.get('redis_service')
    if service is None and current_app.config['USES_SERVICES']:
        service = connect_redis(current_app)
    return service


def connect_redis(app: Flask) -> 'RedisService | None':
    """Build the app's RedisService, or return None and retry on a later call.

    A worker that boots while Redis is unreachable would otherwise stay
    without it for life; once connected, redis-py reconnects by itself.
    """
    now = time.monotonic()
    if now < app.extensions.get('redis_retry_at', 0):
        return None

    try:
        service = RedisService(
            app.config['REDIS_URL'],
            max_connections=app.config['REDIS_MAX_CONNECTIONS'])
    except Exception:
        app.logger.exception(
            'Redis connection failed; retrying in %ss', RECONNECT_INTERVAL_SECONDS)
        app.extensions['redis_retry_at'] = now + RECONNECT_INTERVAL_SECONDS
        return None

    app.extensions['redis_service'] = service
    return service


# Logging in on an 11th device ends the session that would expire soonest
# (with the idle timeout, mostly the one used least recently), so one account
# can never grow its Redis footprint without bound.
MAX_SESSIONS_PER_USER = 10


def _tokens_key(user_id: int) -> str:
    """One sorted set per user: member = refresh-token JTI, score = expiry time"""
    return f'refresh_tokens:{user_id}'


# Records a refresh token, in place of the one it replaces when rotating.
# A script runs inside Redis with nothing else in between, so the check and
# the swap are one step: of two requests rotating the same token at once,
# only the first finds it, and the second is refused (returns 0) rather than
# turning one session into two. Swapping in one step also matters at the
# session cap: storing first would evict another device's session.
#   KEYS[1]  the user's set     ARGV[1]  new JTI       ARGV[2]  its expiry time
#   ARGV[3]  now                ARGV[4]  session cap
#   ARGV[5]  JTI to replace, or '' for a new sign-in
_RECORD_TOKEN = """
if ARGV[5] ~= '' and redis.call('ZREM', KEYS[1], ARGV[5]) == 0 then
  return 0
end
redis.call('ZADD', KEYS[1], ARGV[2], ARGV[1])
redis.call('ZREMRANGEBYSCORE', KEYS[1], '-inf', ARGV[3])
-- Keep the newest sessions; the lowest scores expire first
redis.call('ZREMRANGEBYRANK', KEYS[1], 0, -(tonumber(ARGV[4]) + 1))
-- The key goes when its last token expires. That need not be the token
-- just recorded: one near its session's 30-day cap expires before another
-- device's fresh sign-in.
local last = redis.call('ZRANGE', KEYS[1], -1, -1, 'WITHSCORES')
redis.call('EXPIREAT', KEYS[1], math.ceil(tonumber(last[2])))
return 1
"""


class _Skipped(redis.ConnectionError):
    """Not attempted: Redis was unreachable moments ago"""


class RedisService:
    """Refresh-token allowlist in Redis.

    Redis runs with noeviction because losing these keys logs users out, so
    anything else stored here must carry a TTL, or use a separate instance.

    Every failure is logged: callers turn them into a 503 or a 401, and
    without the log a full Redis (OOM), a wrong password and a key outside
    the ACL user's patterns (NOPERM) would all look the same.

    After a connection failure, calls fail at once for
    RECONNECT_INTERVAL_SECONDS instead of each waiting out the outage, so a
    few requests can't tie up every worker thread.
    """

    def __init__(self, url: str, max_connections: int):
        # A failed ping raises; connect_redis logs it and retries later.
        # rediss:// in the URL turns on TLS.
        self._client = redis.Redis.from_url(
            url,
            decode_responses=True,
            # Ping a connection idle for over 30s before reusing it, so one
            # that Redis or a NAT dropped is replaced instead of failing a request
            health_check_interval=30,
            max_connections=max_connections,
            **REDIS_CLIENT_OPTIONS,
        )
        self._client.ping()
        self._retry_at = 0.0
        # Sent by hash (EVALSHA) after the first call, loaded again if Redis
        # restarted and forgot it
        self._record_token = self._client.register_script(_RECORD_TOKEN)

    def get_client(self) -> redis.Redis:
        """The raw client, for tests that inspect or plant keys"""
        return self._client

    def _check_reachable(self) -> None:
        if time.monotonic() < self._retry_at:
            raise _Skipped('Redis was unreachable; not retrying yet')

    def _failed(self, error: redis.RedisError, message: str, user_id: int) -> None:
        """Log a failure, and stop calling Redis for a while if it is unreachable"""
        if isinstance(error, _Skipped):
            return  # logged when the connection failed
        if isinstance(error, (redis.ConnectionError, redis.TimeoutError)):
            self._retry_at = time.monotonic() + RECONNECT_INTERVAL_SECONDS
        current_app.logger.exception(message, user_id)

    def _record(self, user_id: int, jti: str, ttl_seconds: int, replaces: str) -> bool:
        self._check_reachable()
        now = time.time()
        recorded = self._record_token(
            keys=[_tokens_key(user_id)],
            args=[jti, now + ttl_seconds, now, MAX_SESSIONS_PER_USER, replaces])
        return recorded == 1

    def store_refresh_token(self, user_id: int, jti: str, ttl_seconds: int) -> bool | None:
        """Record a new sign-in's refresh token; None if Redis failed"""
        try:
            return self._record(user_id, jti, ttl_seconds, replaces='')
        except redis.RedisError as error:
            self._failed(error, 'Could not record a refresh token for user %s', user_id)
            return None

    def rotate_refresh_token(self, user_id: int, old_jti: str, new_jti: str,
                             ttl_seconds: int) -> bool | None:
        """Swap a refresh token for its successor.

        False if `old_jti` was no longer there (another request rotated it
        first, or it was revoked), and None if Redis failed: the caller must
        tell those apart, since only the first means the session is over.
        """
        try:
            return self._record(user_id, new_jti, ttl_seconds, replaces=old_jti)
        except redis.RedisError as error:
            self._failed(error, 'Could not rotate a refresh token for user %s', user_id)
            return None

    def is_token_valid(self, user_id: int, jti: str) -> bool | None:
        """Whether the refresh token is live; None if Redis failed.

        None is not False: the token may be fine, and calling it revoked would
        sign the user out over an outage.
        """
        try:
            self._check_reachable()
            expires_at = self._client.zscore(_tokens_key(user_id), jti)
            return expires_at is not None and expires_at > time.time()
        except redis.RedisError as error:
            self._failed(error, 'Could not check a refresh token for user %s', user_id)
            return None

    def revoke_token(self, user_id: int, jti: str) -> None:
        """End one session. Logout is best effort, so a failure is only logged."""
        try:
            self._check_reachable()
            self._client.zrem(_tokens_key(user_id), jti)
        except redis.RedisError as error:
            self._failed(error, 'Could not revoke a refresh token for user %s', user_id)

    def revoke_all_user_tokens(self, user_id: int) -> int | None:
        """Revoke every session the user has.

        Returns how many were live, or None if Redis failed, which the caller
        must not report as success: the sessions are all still valid.
        """
        key = _tokens_key(user_id)
        try:
            self._check_reachable()
            pipe = self._client.pipeline()
            pipe.zcount(key, time.time(), '+inf')
            pipe.delete(key)
            live, _ = pipe.execute()
            return live
        except redis.RedisError as error:
            self._failed(error, 'Could not revoke the sessions of user %s', user_id)
            return None
