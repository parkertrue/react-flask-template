import json
import threading
import time

from flask_jwt_extended import decode_token

from app.utils.redis_service import MAX_SESSIONS_PER_USER


LOGIN_PAYLOAD = {
    'email': 'integration@test.com',
    'password': 'TestPassword123'
}


def _login(client):
    return client.post(
        '/api/auth/login',
        data=json.dumps(LOGIN_PAYLOAD),
        content_type='application/json'
    )


def _keys(user_id):
    """The user's sorted set of sessions, and the hash of their details"""
    return f'refresh_tokens:{{{user_id}}}', f'refresh_tokens:{{{user_id}}}:sessions'


def _sessions(redis_service, user_id):
    """The user's sessions as (id, current JTI), soonest-expiring first; a
    session in one key and not the other is a bug, so both must agree"""
    zset, details = _keys(user_id)
    client = redis_service.get_client()
    ids = client.zrange(zset, 0, -1)
    stored = client.hgetall(details)
    assert sorted(stored) == sorted(ids)
    return [(session_id, json.loads(stored[session_id])['jti']) for session_id in ids]


def _ids(redis_service, user_id):
    return [session_id for session_id, _ in _sessions(redis_service, user_id)]


class TestRedisTokenStorage:
    """Sessions in Redis, under the app's ACL user"""

    def test_login_stores_a_session(self, integration_client, integration_user, integration_redis):
        response = integration_client.post(
            '/api/auth/login', json=LOGIN_PAYLOAD, headers={'User-Agent': 'curl/8.0'})

        assert response.status_code == 200
        [(session_id, jti)] = _sessions(integration_redis, integration_user.id)
        cookie = integration_client.get_cookie('__Secure-refresh_token', path='/api/auth').value
        with integration_client.application.app_context():
            claims = decode_token(cookie)
        assert (session_id, jti) == (claims['sid'], claims['jti'])
        [listed] = integration_redis.list_sessions(integration_user.id)
        assert (listed['id'], listed['device']) == (session_id, 'curl')

    def test_logout_ends_the_session(self, integration_client, integration_user, integration_redis):
        assert _login(integration_client).status_code == 200

        integration_client.post('/api/auth/logout')

        assert _sessions(integration_redis, integration_user.id) == []

    def test_logout_all_ends_every_session(self, integration_client, integration_user, integration_redis):
        for _ in range(3):
            _login(integration_client)
        assert len(_sessions(integration_redis, integration_user.id)) == 3

        integration_client.post('/api/auth/logout-all')

        assert _sessions(integration_redis, integration_user.id) == []

    def test_one_session_ends_from_another_device(
            self, integration_client, integration_user, integration_redis):
        for _ in range(2):
            _login(integration_client)
        first, second = _ids(integration_redis, integration_user.id)

        assert integration_redis.revoke_session(integration_user.id, first) is True
        assert integration_redis.revoke_session(integration_user.id, first) is False
        assert _ids(integration_redis, integration_user.id) == [second]


class TestSessionBounds:
    """A user's sessions stay bounded however often they log in"""

    def test_logins_beyond_the_cap_evict_the_oldest_session(
        self, integration_client, integration_user, integration_redis
    ):
        _login(integration_client)
        _login(integration_client)
        first_two = _ids(integration_redis, integration_user.id)

        for _ in range(MAX_SESSIONS_PER_USER):
            _login(integration_client)

        ids = _ids(integration_redis, integration_user.id)
        assert len(ids) == MAX_SESSIONS_PER_USER
        assert not set(first_two) & set(ids)

    def test_expired_sessions_are_pruned_on_the_next_login(
        self, integration_client, integration_user, integration_redis
    ):
        zset, details = _keys(integration_user.id)
        integration_redis.get_client().zadd(zset, {'stale': time.time() - 1})
        integration_redis.get_client().hset(details, 'stale', json.dumps({'jti': 'old'}))

        _login(integration_client)

        assert 'stale' not in _ids(integration_redis, integration_user.id)

    def test_keys_expire_with_the_newest_session(
        self, integration_client, integration_user, integration_redis
    ):
        _login(integration_client)

        for key in _keys(integration_user.id):
            # The script rounds the expiry up to a whole second
            assert 6 * 24 * 3600 < integration_redis.get_client().ttl(key) <= 7 * 24 * 3600 + 1

    def test_keys_outlive_a_shorter_token_recorded_after_a_longer_one(
        self, integration_user, integration_redis
    ):
        """A session near its 30-day cap rotates to a token that expires
        before another device's: the keys must keep that device's session"""
        user_id = integration_user.id
        integration_redis.store_refresh_token(user_id, 'fresh-device', 'a', 7 * 24 * 3600, device='x')
        integration_redis.store_refresh_token(user_id, 'ending-session', 'b', 3600, device='y')

        integration_redis.rotate_refresh_token(user_id, 'ending-session', 'b', 'last-hour', 3600)

        for key in _keys(user_id):
            assert 7 * 24 * 3600 - 60 < integration_redis.get_client().ttl(key) <= 7 * 24 * 3600 + 1

    def test_logout_all_reports_live_sessions(
        self, integration_client, integration_user, integration_redis
    ):
        for _ in range(3):
            _login(integration_client)

        response = integration_client.post('/api/auth/logout-all')

        assert response.get_json()['message'] == 'Logged out from 3 device(s)'


class TestTokenRotation:
    """A refresh swaps the session's token, keeping the session"""

    def test_refresh_replaces_the_session_s_token(
        self, integration_client, integration_user, integration_redis
    ):
        assert _login(integration_client).status_code == 200
        [(session_id, old_jti)] = _sessions(integration_redis, integration_user.id)
        [before] = integration_redis.list_sessions(integration_user.id)
        time.sleep(1.1)

        assert integration_client.post('/api/auth/refresh').status_code == 200

        [(same_id, new_jti)] = _sessions(integration_redis, integration_user.id)
        [after] = integration_redis.list_sessions(integration_user.id)
        assert same_id == session_id
        assert new_jti != old_jti
        assert after['signed_in_at'] == before['signed_in_at']
        assert after['last_active_at'] > before['last_active_at']

    def test_refresh_at_the_session_cap_keeps_other_sessions(
        self, integration_client, integration_user, integration_redis
    ):
        """Rotation swaps one token for another; it must not evict a device"""
        for _ in range(MAX_SESSIONS_PER_USER):
            _login(integration_client)
        before = _sessions(integration_redis, integration_user.id)

        assert integration_client.post('/api/auth/refresh').status_code == 200

        after = _sessions(integration_redis, integration_user.id)
        assert sorted(session_id for session_id, _ in after) == sorted(session_id for session_id, _ in before)
        # Only the client's own session, the newest login, has a new token
        assert len(set(after) - set(before)) == 1


class TestRotationIsAtomic:
    """One refresh token buys one successor, however many requests race for it"""

    def test_a_token_rotates_only_once(
        self, integration_client, integration_user, integration_redis
    ):
        assert _login(integration_client).status_code == 200
        [(session_id, old)] = _sessions(integration_redis, integration_user.id)

        first = integration_redis.rotate_refresh_token(integration_user.id, session_id, old, 'next-1', 60)
        second = integration_redis.rotate_refresh_token(integration_user.id, session_id, old, 'next-2', 60)

        assert (first, second) == (True, False)
        assert _sessions(integration_redis, integration_user.id) == [(session_id, 'next-1')]

    def test_concurrent_refreshes_yield_exactly_one_session(
        self, integration_app, integration_client, integration_user, integration_redis
    ):
        """Whichever loses, at the blocklist or in the rotation, it gets a 401"""
        assert _login(integration_client).status_code == 200
        cookie = integration_client.get_cookie('__Secure-refresh_token', path='/api/auth').value
        start = threading.Barrier(2)
        statuses = []

        def refresh():
            client = integration_app.test_client(use_cookies=False)
            start.wait()
            response = client.post(
                '/api/auth/refresh', headers={'Cookie': f'__Secure-refresh_token={cookie}'})
            statuses.append(response.status_code)

        threads = [threading.Thread(target=refresh) for _ in range(2)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()

        assert sorted(statuses) == [200, 401]
        assert len(_sessions(integration_redis, integration_user.id)) == 1


class TestBlocklistFailsClosed:
    """The blocklist must reject tokens it cannot verify"""

    def test_revoked_refresh_token_is_rejected(
        self, integration_client, integration_user, integration_redis
    ):
        """A session deleted from Redis must no longer refresh"""
        assert _login(integration_client).status_code == 200

        integration_redis.get_client().delete(*_keys(integration_user.id))

        response = integration_client.post('/api/auth/refresh')
        assert response.status_code == 401


class TestUsedLinks:
    """A sign-up link works once: claimed on real Redis, as the app's ACL
    user, which may write used_links:* (test_redis_acl.py)"""

    def test_a_link_is_claimed_once_for_its_lifetime(self, integration_app, integration_redis):
        with integration_app.app_context():
            first = integration_redis.claim_link('integration.link.token', ttl_seconds=86400)
            again = integration_redis.claim_link('integration.link.token', ttl_seconds=86400)
        # SCAN, not KEYS, which the app's user may not run
        [key] = integration_redis.get_client().scan_iter('used_links:*')

        assert (first, again) == (True, False)
        assert 86390 <= integration_redis.get_client().ttl(key) <= 86400

    def test_a_released_link_can_be_claimed_again(self, integration_app, integration_redis):
        with integration_app.app_context():
            integration_redis.claim_link('integration.link.token', ttl_seconds=86400)
            integration_redis.release_link('integration.link.token')

            assert integration_redis.claim_link('integration.link.token', ttl_seconds=86400) is True
