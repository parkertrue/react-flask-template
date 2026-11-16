import json
import threading
import time

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


def _jtis(redis_service, user_id):
    """The user's stored refresh-token JTIs, soonest-expiring first"""
    return redis_service.get_client().zrange(f'refresh_tokens:{user_id}', 0, -1)


class TestRedisTokenStorage:
    """Test token storage in Redis"""

    def test_login_stores_refresh_token_in_redis(
        self, integration_client, integration_user, integration_redis
    ):
        """Login should store the refresh token JTI in Redis"""
        response = _login(integration_client)

        assert response.status_code == 200

        cookies = response.headers.getlist('Set-Cookie')
        refresh_cookie = next(
            (c for c in cookies if '__Secure-refresh_token' in c), None)
        assert refresh_cookie is not None

        assert len(_jtis(integration_redis, integration_user.id)) == 1

    def test_logout_revokes_token_in_redis(
        self, integration_client, integration_user, integration_redis
    ):
        """Logout should remove the refresh token from Redis"""
        assert _login(integration_client).status_code == 200
        assert len(_jtis(integration_redis, integration_user.id)) == 1

        integration_client.post('/api/auth/logout')

        assert len(_jtis(integration_redis, integration_user.id)) == 0

    def test_logout_all_revokes_all_user_tokens(
        self, integration_client, integration_user, integration_redis
    ):
        """Logout-all should remove every token for the user"""
        # Simulate three separate devices
        for _ in range(3):
            _login(integration_client)

        assert len(_jtis(integration_redis, integration_user.id)) == 3

        integration_client.post('/api/auth/logout-all')

        assert len(_jtis(integration_redis, integration_user.id)) == 0


class TestSessionBounds:
    """A user's token set stays bounded however often they log in"""

    def test_logins_beyond_the_cap_evict_the_oldest_session(
        self, integration_client, integration_user, integration_redis
    ):
        _login(integration_client)
        _login(integration_client)
        first_two = _jtis(integration_redis, integration_user.id)

        for _ in range(MAX_SESSIONS_PER_USER):
            _login(integration_client)

        jtis = _jtis(integration_redis, integration_user.id)
        assert len(jtis) == MAX_SESSIONS_PER_USER
        assert not set(first_two) & set(jtis)

    def test_expired_entries_are_pruned_on_the_next_login(
        self, integration_client, integration_user, integration_redis
    ):
        key = f'refresh_tokens:{integration_user.id}'
        integration_redis.get_client().zadd(key, {'stale': time.time() - 1})

        _login(integration_client)

        assert 'stale' not in _jtis(integration_redis, integration_user.id)

    def test_key_expires_with_the_newest_token(
        self, integration_client, integration_user, integration_redis
    ):
        _login(integration_client)

        ttl = integration_redis.get_client().ttl(
            f'refresh_tokens:{integration_user.id}')
        # The script rounds the expiry up to a whole second
        assert 6 * 24 * 3600 < ttl <= 7 * 24 * 3600 + 1

    def test_key_outlives_a_shorter_token_recorded_after_a_longer_one(
        self, integration_user, integration_redis
    ):
        """A session near its 30-day cap rotates to a token that expires
        before another device's: the key must keep that device's session"""
        user_id = integration_user.id
        integration_redis.store_refresh_token(user_id, 'fresh-device', 7 * 24 * 3600)
        integration_redis.store_refresh_token(user_id, 'ending-session', 3600)

        integration_redis.rotate_refresh_token(user_id, 'ending-session', 'last-hour', 3600)

        ttl = integration_redis.get_client().ttl(f'refresh_tokens:{user_id}')
        assert 7 * 24 * 3600 - 60 < ttl <= 7 * 24 * 3600 + 1

    def test_logout_all_reports_live_sessions(
        self, integration_client, integration_user, integration_redis
    ):
        for _ in range(3):
            _login(integration_client)

        response = integration_client.post('/api/auth/logout-all')

        assert response.get_json()['message'] == 'Logged out from 3 device(s)'


class TestTokenRotation:
    """Test refresh token rotation"""

    def test_refresh_revokes_old_token(
        self, integration_client, integration_user, integration_redis
    ):
        """Refreshing should revoke the old token and issue exactly one new one"""
        assert _login(integration_client).status_code == 200

        [old_jti] = _jtis(integration_redis, integration_user.id)

        refresh_response = integration_client.post('/api/auth/refresh')
        assert refresh_response.status_code == 200

        [new_jti] = _jtis(integration_redis, integration_user.id)
        assert old_jti != new_jti

    def test_refresh_at_the_session_cap_keeps_other_sessions(
        self, integration_client, integration_user, integration_redis
    ):
        """Rotation swaps one token for another; it must not evict a device"""
        for _ in range(MAX_SESSIONS_PER_USER):
            _login(integration_client)
        before = _jtis(integration_redis, integration_user.id)
        current = before[-1]  # the client's cookie holds the newest login

        assert integration_client.post('/api/auth/refresh').status_code == 200

        after = _jtis(integration_redis, integration_user.id)
        assert len(after) == MAX_SESSIONS_PER_USER
        assert current not in after
        assert set(before) - {current} <= set(after)


class TestRotationIsAtomic:
    """One refresh token buys one successor, however many requests race for it"""

    def test_a_token_rotates_only_once(
        self, integration_client, integration_user, integration_redis
    ):
        assert _login(integration_client).status_code == 200
        [old] = _jtis(integration_redis, integration_user.id)

        first = integration_redis.rotate_refresh_token(integration_user.id, old, 'next-1', 60)
        second = integration_redis.rotate_refresh_token(integration_user.id, old, 'next-2', 60)

        assert (first, second) == (True, False)
        assert _jtis(integration_redis, integration_user.id) == ['next-1']

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
        assert len(_jtis(integration_redis, integration_user.id)) == 1


class TestBlocklistFailsClosed:
    """The blocklist must reject tokens it cannot verify"""

    def test_revoked_refresh_token_is_rejected(
        self, integration_client, integration_user, integration_redis
    ):
        """A refresh token deleted from Redis must no longer be accepted"""
        assert _login(integration_client).status_code == 200

        integration_redis.get_client().delete(
            f'refresh_tokens:{integration_user.id}')

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
