"""The account's sessions: what each sign-in records, how refresh and logout
keep it, and GET/DELETE /api/account/sessions"""
import json

import pytest
from flask_jwt_extended import create_access_token, create_refresh_token, decode_token

from tests.unit.utils.test_devices import EDGE_MAC, FIREFOX_WINDOWS

PASSWORD = 'TestPassword123'  # sample_user's


class Device:
    """One browser signed in to sample_user's account: its own cookie jar"""

    def __init__(self, app, user_agent=FIREFOX_WINDOWS):
        self.client = app.test_client()
        self.user_agent = user_agent
        response = self.client.post('/api/auth/login', headers={'User-Agent': user_agent},
                                    json={'email': 'test@example.com', 'password': PASSWORD})
        assert response.status_code == 200
        self.access = response.get_json()['access_token']
        self.csrf = response.get_json()['refresh_csrf']

    @property
    def headers(self):
        return {'Authorization': f'Bearer {self.access}'}

    @property
    def session_id(self):
        return decode_token(self.access)['sid']

    def refresh(self):
        response = self.client.post('/api/auth/refresh', headers={
            'X-CSRF-REFRESH-TOKEN': self.csrf, 'User-Agent': self.user_agent})
        if response.status_code == 200:
            self.access = response.get_json()['access_token']
            self.csrf = response.get_json()['refresh_csrf']
        return response

    def refresh_claims(self):
        return decode_token(self.client.get_cookie('__Secure-refresh_token', path='/api/auth').value)

    def sessions(self):
        return self.client.get('/api/account/sessions', headers=self.headers)

    def end(self, session_id):
        return self.client.delete(f'/api/account/sessions/{session_id}', headers=self.headers)


@pytest.fixture
def clock(fake_redis, monkeypatch):
    """The token store's clock, moved by hand"""
    now = [1_800_000_000]
    fake_redis.clock = lambda: now[0]
    return now


class TestSessionRecords:
    def test_a_sign_in_starts_a_session_named_by_its_device(self, app, sample_user, fake_redis, clock):
        device = Device(app)

        assert fake_redis.sessions == {(sample_user.id, device.session_id): {
            'jti': device.refresh_claims()['jti'], 'device': 'Firefox on Windows',
            'signed_in_at': clock[0], 'last_active_at': clock[0]}}

    def test_both_tokens_name_the_session(self, app, sample_user, fake_redis):
        device = Device(app)

        assert device.refresh_claims()['sid'] == device.session_id

    def test_each_sign_in_is_its_own_session(self, app, sample_user, fake_redis):
        first, second = Device(app), Device(app)

        assert first.session_id != second.session_id
        assert len(fake_redis.sessions) == 2

    def test_a_refresh_keeps_the_session_and_marks_it_active(self, app, sample_user, fake_redis, clock):
        device = Device(app)
        session_id, signed_in = device.session_id, clock[0]
        clock[0] += 600

        assert device.refresh().status_code == 200

        assert device.session_id == session_id
        assert fake_redis.sessions[(sample_user.id, session_id)] == {
            'jti': device.refresh_claims()['jti'], 'device': 'Firefox on Windows',
            'signed_in_at': signed_in, 'last_active_at': signed_in + 600}

    def test_a_refresh_token_without_a_session_is_refused(self, app, client, sample_user, fake_redis):
        """Issued before tokens named their session: its holder logs in again"""
        device = Device(app)
        with app.app_context():
            token = create_refresh_token(identity=str(sample_user.id), additional_claims={'auth_time': 1})
        device.client.set_cookie('__Secure-refresh_token', token, path='/api/auth')

        response = device.client.post('/api/auth/refresh', headers={
            'X-CSRF-REFRESH-TOKEN': decode_token(token)['csrf']})

        assert response.status_code == 401
        assert response.get_json()['error']['code'] == 'AUTH_TOKEN_REVOKED'

    def test_logout_ends_this_session_alone(self, app, sample_user, fake_redis):
        leaving, staying = Device(app), Device(app)

        leaving.client.post('/api/auth/logout', headers={'X-CSRF-REFRESH-TOKEN': leaving.csrf})

        assert set(fake_redis.sessions) == {(sample_user.id, staying.session_id)}


class TestListSessions:
    """GET /api/account/sessions"""

    def test_lists_the_live_sessions_most_recently_active_first(self, app, sample_user, fake_redis, clock):
        laptop = Device(app, FIREFOX_WINDOWS)
        clock[0] += 60
        desktop = Device(app, EDGE_MAC)
        clock[0] += 60
        laptop.refresh()

        response = desktop.sessions()

        assert response.status_code == 200
        assert response.get_json() == {'sessions': [
            {'id': laptop.session_id, 'device': 'Firefox on Windows',
             'signed_in_at': '2027-01-15T08:00:00+00:00', 'last_active_at': '2027-01-15T08:02:00+00:00',
             'current': False},
            {'id': desktop.session_id, 'device': 'Edge on macOS',
             'signed_in_at': '2027-01-15T08:01:00+00:00', 'last_active_at': '2027-01-15T08:01:00+00:00',
             'current': True},
        ]}

    def test_another_account_s_sessions_are_not_listed(
            self, app, sample_user, second_user, fake_redis, client, second_auth_headers):
        Device(app)

        response = client.get('/api/account/sessions', headers=second_auth_headers)

        assert response.get_json() == {'sessions': []}

    def test_a_token_without_a_session_marks_none_current(self, app, client, sample_user, fake_redis):
        """An access token minted before tokens named their session"""
        Device(app)
        with app.app_context():
            token = create_access_token(identity=str(sample_user.id))

        response = client.get('/api/account/sessions', headers={'Authorization': f'Bearer {token}'})

        assert [session['current'] for session in response.get_json()['sessions']] == [False]

    def test_without_redis_is_a_503(self, app, client, sample_user, auth_headers, no_redis):
        response = client.get('/api/account/sessions', headers=auth_headers)

        assert response.status_code == 503
        assert response.get_json()['error']['code'] == 'SERVICE_UNAVAILABLE'

    def test_requires_a_session(self, client):
        assert client.get('/api/account/sessions').status_code == 401


class TestEndSession:
    """DELETE /api/account/sessions/<id>"""

    def test_ends_that_session_alone(self, app, sample_user, fake_redis, security_events):
        here, there, elsewhere = Device(app), Device(app), Device(app)

        response = here.end(there.session_id)

        assert response.status_code == 200
        assert response.get_json() == {'message': 'Logged out'}
        assert set(fake_redis.sessions) == {
            (sample_user.id, here.session_id), (sample_user.id, elsewhere.session_id)}
        assert security_events()[-1] == {
            'message': 'session_revoked', 'ip': '127.0.0.1', 'user_id': sample_user.id}

    def test_that_device_can_no_longer_refresh(self, app, sample_user, fake_redis):
        here, there = Device(app), Device(app)

        here.end(there.session_id)

        response = there.refresh()
        assert response.status_code == 401
        assert response.get_json()['error']['code'] == 'AUTH_TOKEN_REVOKED'

    @pytest.mark.parametrize('session_id', ['no-such-session', 'x' * 65, 'a b'],
                             ids=['unknown', 'too long', 'not an id'])
    def test_a_session_it_does_not_have(self, app, sample_user, fake_redis, session_id):
        here = Device(app)

        response = here.end(session_id)

        assert response.status_code == 404
        assert len(fake_redis.sessions) == 1

    def test_another_account_s_session_is_a_404_alike(
            self, app, client, sample_user, second_user, fake_redis, second_auth_headers):
        theirs = Device(app)

        response = client.delete(f'/api/account/sessions/{theirs.session_id}', headers=second_auth_headers)

        assert response.status_code == 404
        assert response.get_json()['error']['code'] == 'NOT_FOUND'
        assert len(fake_redis.sessions) == 1

    def test_without_redis_nothing_ends(self, app, sample_user, fake_redis):
        here, there = Device(app), Device(app)
        app.extensions['redis_service'] = None

        response = here.end(there.session_id)

        assert response.status_code == 503
        assert response.get_json()['error'] == {
            'code': 'SERVICE_UNAVAILABLE',
            'message': 'Could not log out that device, please try again shortly'}
        app.extensions['redis_service'] = fake_redis
        assert len(fake_redis.sessions) == 2

    def test_requires_a_session(self, client):
        assert client.delete('/api/account/sessions/abc').status_code == 401

    def test_logs_no_session_id(self, app, sample_user, fake_redis, logged):
        here, there = Device(app), Device(app)

        here.end(there.session_id)

        assert there.session_id not in json.dumps(logged())
