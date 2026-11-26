import hashlib
import json
import time
from typing import TypedDict

import redis
from redis.backoff import NoBackoff
from redis.retry import Retry
from flask import Flask, current_app

# How long to wait after a failed connection before trying again. Each attempt
# can block a request for several seconds while Redis is down: the timeouts
# below don't cover looking up the name of a stopped container, which can
# take seconds on its own. Every call a request makes to Redis (the token
# store here, the job queue in jobs.py) skips it meanwhile; the rate limiter
# keeps its own back-off.
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


def redis_unreachable(app: Flask) -> bool:
    """Whether a call to Redis failed to connect within the last
    RECONNECT_INTERVAL_SECONDS, so the next one should not try"""
    retry_at: float = app.extensions.get('redis_retry_at', 0.0)
    return time.monotonic() < retry_at


def mark_redis_unreachable(app: Flask) -> None:
    """Make the app's calls to Redis fail at once for RECONNECT_INTERVAL_SECONDS"""
    app.extensions['redis_retry_at'] = time.monotonic() + RECONNECT_INTERVAL_SECONDS


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
    if redis_unreachable(app):
        return None

    try:
        service = RedisService(
            app.config['REDIS_URL'],
            max_connections=app.config['REDIS_MAX_CONNECTIONS'])
    except Exception:
        app.logger.exception(
            'Redis connection failed; retrying in %ss', RECONNECT_INTERVAL_SECONDS)
        mark_redis_unreachable(app)
        return None

    app.extensions['redis_service'] = service
    return service


# Logging in on an 11th device ends the session that would expire soonest
# (with the idle timeout, mostly the one used least recently), so one account
# can never grow its Redis footprint without bound.
MAX_SESSIONS_PER_USER = 10


def _tokens_key(user_id: int) -> str:
    """One sorted set per user: member = session id, score = when it expires.

    The braces are a hash tag: a clustered Redis keeps both of a user's keys
    on one node, as the script below, which touches both, requires.
    """
    return f'refresh_tokens:{{{user_id}}}'


def _sessions_key(user_id: int) -> str:
    """One hash per user: field = session id, value = the session as JSON
    (its current refresh token's JTI, its device, when it signed in and when
    it was last active). Under the same prefix as the sorted set, so the app's
    Redis user may touch it with no change to its ACL."""
    return f'refresh_tokens:{{{user_id}}}:sessions'


class Session(TypedDict):
    """A live session, as the account page lists it"""
    id: str
    device: str
    signed_in_at: int
    last_active_at: int


def _used_link_key(token: str) -> str:
    """One key per emailed link once used: a hash of its token, never the
    token, which a reader of Redis could otherwise use"""
    return f'used_links:{hashlib.sha256(token.encode()).hexdigest()}'


# Records a session's refresh token: a new session, or a rotation, which
# replaces the session's current token. A script runs inside Redis with
# nothing else in between, so the check and the swap are one step: of two
# requests rotating the same token at once, only the first finds it current,
# and the second is refused (returns 0) rather than turning one session into
# two. Swapping in one step also matters at the session cap: storing first
# would evict another device's session.
#   KEYS[1]  the user's sorted set       KEYS[2]  the user's session hash
#   ARGV[1]  session id                  ARGV[2]  new JTI
#   ARGV[3]  its expiry time             ARGV[4]  now
#   ARGV[5]  session cap                 ARGV[6]  JTI to replace, or '' for a
#                                                 new session
#   ARGV[7]  a new session's device      ARGV[8]  when it signed in
_RECORD_TOKEN = """
local session
if ARGV[6] ~= '' then
  local raw = redis.call('HGET', KEYS[2], ARGV[1])
  if not raw then return 0 end
  session = cjson.decode(raw)
  if session.jti ~= ARGV[6] then return 0 end
else
  session = {device = ARGV[7], signed_in_at = tonumber(ARGV[8])}
end
session.jti = ARGV[2]
session.last_active_at = math.floor(tonumber(ARGV[4]))
redis.call('HSET', KEYS[2], ARGV[1], cjson.encode(session))
redis.call('ZADD', KEYS[1], ARGV[3], ARGV[1])
-- Drop the expired sessions, and the oldest past the cap (the lowest
-- scores expire first), from both keys
local gone = redis.call('ZRANGEBYSCORE', KEYS[1], '-inf', ARGV[4])
for _, id in ipairs(redis.call('ZRANGE', KEYS[1], 0, -(tonumber(ARGV[5]) + 1))) do
  table.insert(gone, id)
end
for _, id in ipairs(gone) do
  redis.call('ZREM', KEYS[1], id)
  redis.call('HDEL', KEYS[2], id)
end
-- The keys go when their last session expires. That need not be the one
-- just recorded: one near its 30-day cap expires before another device's
-- fresh sign-in.
local last = redis.call('ZRANGE', KEYS[1], -1, -1, 'WITHSCORES')
local expires = math.ceil(tonumber(last[2]))
redis.call('EXPIREAT', KEYS[1], expires)
redis.call('EXPIREAT', KEYS[2], expires)
return 1
"""


class _Skipped(redis.ConnectionError):
    """Not attempted: Redis was unreachable moments ago"""


class RedisService:
    """Refresh-token allowlist in Redis, by session: each sign-in is a session,
    whose refresh token rotates on every refresh.

    Redis runs with noeviction because losing these keys logs users out, so
    anything else stored here must carry a TTL, or go once used, as the job
    queue's messages do (jobs.py), or use a separate instance.

    Every failure is logged: callers turn them into a 503 or a 401, and
    without the log a full Redis (OOM), a wrong password and a key outside
    the ACL user's patterns (NOPERM) would all look the same.

    After a connection failure, here or in the job queue, calls fail at once
    for RECONNECT_INTERVAL_SECONDS instead of each waiting out the outage, so
    a few requests can't tie up every worker thread.
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
        # Sent by hash (EVALSHA) after the first call, loaded again if Redis
        # restarted and forgot it
        self._record_token = self._client.register_script(_RECORD_TOKEN)

    def get_client(self) -> redis.Redis:
        """The raw client, for tests that inspect or plant keys"""
        return self._client

    def _check_reachable(self) -> None:
        if redis_unreachable(current_app):
            raise _Skipped('Redis was unreachable; not retrying yet')

    def _failed(self, error: redis.RedisError, message: str, *args: object) -> None:
        """Log a failure, and stop calling Redis for a while if it is unreachable"""
        if isinstance(error, _Skipped):
            return  # logged when the connection failed
        if isinstance(error, (redis.ConnectionError, redis.TimeoutError)):
            mark_redis_unreachable(current_app)
        current_app.logger.exception(message, *args)

    def _record(self, user_id: int, session_id: str, jti: str, ttl_seconds: int,
                replaces: str = '', device: str = '') -> bool:
        self._check_reachable()
        now = time.time()
        recorded = self._record_token(
            keys=[_tokens_key(user_id), _sessions_key(user_id)],
            args=[session_id, jti, now + ttl_seconds, now, MAX_SESSIONS_PER_USER, replaces,
                  device, int(now)])
        return bool(recorded == 1)

    def store_refresh_token(self, user_id: int, session_id: str, jti: str, ttl_seconds: int,
                            device: str) -> bool | None:
        """Record a new sign-in: its session, and its first refresh token.
        None if Redis failed."""
        try:
            return self._record(user_id, session_id, jti, ttl_seconds, device=device)
        except redis.RedisError as error:
            self._failed(error, 'Could not record a refresh token for user %s', user_id)
            return None

    def rotate_refresh_token(self, user_id: int, session_id: str, old_jti: str, new_jti: str,
                             ttl_seconds: int) -> bool | None:
        """Swap a session's refresh token for its successor, and mark the
        session active now.

        False if `old_jti` was no longer the session's (another request rotated
        it first, or the session ended), and None if Redis failed: the caller
        must tell those apart, since only the first means the session is over.
        """
        try:
            return self._record(user_id, session_id, new_jti, ttl_seconds, replaces=old_jti)
        except redis.RedisError as error:
            self._failed(error, 'Could not rotate a refresh token for user %s', user_id)
            return None

    def is_token_valid(self, user_id: int, session_id: str, jti: str) -> bool | None:
        """Whether the refresh token is its session's current one, and the
        session is live; None if Redis failed.

        None is not False: the token may be fine, and calling it revoked would
        sign the user out over an outage.
        """
        try:
            self._check_reachable()
            pipe = self._client.pipeline()
            pipe.zscore(_tokens_key(user_id), session_id)
            pipe.hget(_sessions_key(user_id), session_id)
            expires_at, raw = pipe.execute()
            return (expires_at is not None and expires_at > time.time() and raw is not None
                    and json.loads(raw).get('jti') == jti)
        except redis.RedisError as error:
            self._failed(error, 'Could not check a refresh token for user %s', user_id)
            return None

    def is_session_live(self, user_id: int, session_id: str) -> bool | None:
        """Whether the session is live, for an access token naming it; None if
        Redis failed, which the caller treats as live (app/__init__.py)"""
        try:
            self._check_reachable()
            expires_at = self._client.zscore(_tokens_key(user_id), session_id)
            return expires_at is not None and expires_at > time.time()
        except redis.RedisError as error:
            self._failed(error, 'Could not check a session of user %s', user_id)
            return None

    def _end_session(self, user_id: int, session_id: str) -> bool:
        """End one session; whether it was live"""
        self._check_reachable()
        pipe = self._client.pipeline()
        pipe.zscore(_tokens_key(user_id), session_id)
        pipe.zrem(_tokens_key(user_id), session_id)
        pipe.hdel(_sessions_key(user_id), session_id)
        expires_at, _, _ = pipe.execute()
        return expires_at is not None and expires_at > time.time()

    def revoke_token(self, user_id: int, session_id: str) -> None:
        """End this device's session. Logout is best effort, so a failure is
        only logged."""
        try:
            self._end_session(user_id, session_id)
        except redis.RedisError as error:
            self._failed(error, 'Could not revoke a refresh token for user %s', user_id)

    def revoke_session(self, user_id: int, session_id: str) -> bool | None:
        """End one of the user's sessions, from another device: whether it was
        live, or None if Redis failed, which the caller must not report as
        done (the session is still valid)."""
        try:
            return self._end_session(user_id, session_id)
        except redis.RedisError as error:
            self._failed(error, 'Could not revoke a session of user %s', user_id)
            return None

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
            pipe.delete(key, _sessions_key(user_id))
            live, _ = pipe.execute()
            return int(live)
        except redis.RedisError as error:
            self._failed(error, 'Could not revoke the sessions of user %s', user_id)
            return None

    def list_sessions(self, user_id: int) -> list[Session] | None:
        """The user's live sessions, most recently active first; None if
        Redis failed"""
        try:
            self._check_reachable()
            pipe = self._client.pipeline()
            pipe.zrangebyscore(_tokens_key(user_id), time.time(), '+inf')
            pipe.hgetall(_sessions_key(user_id))
            live, details = pipe.execute()
        except redis.RedisError as error:
            self._failed(error, 'Could not list the sessions of user %s', user_id)
            return None
        sessions: list[Session] = []
        for session_id in live:
            raw = details.get(session_id)
            if raw is None:
                continue
            session = json.loads(raw)
            sessions.append(Session(
                id=session_id, device=session['device'], signed_in_at=session['signed_in_at'],
                last_active_at=session['last_active_at']))
        return sorted(sessions, key=lambda each: each['last_active_at'], reverse=True)

    def claim_link(self, token: str, ttl_seconds: int) -> bool | None:
        """Mark an emailed link used, for as long as it could still work.

        False if it was used already, None if Redis failed: a link must work
        once, so the caller refuses it either way.
        """
        try:
            self._check_reachable()
            return bool(self._client.set(_used_link_key(token), 1, nx=True, ex=ttl_seconds))
        except redis.RedisError as error:
            self._failed(error, 'Could not mark a link used')
            return None

    def release_link(self, token: str) -> None:
        """Let a claimed link work again: what it was used for failed"""
        try:
            self._check_reachable()
            self._client.delete(_used_link_key(token))
        except redis.RedisError as error:
            self._failed(error, 'Could not release a used link')
