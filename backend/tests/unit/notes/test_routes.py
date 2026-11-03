import pytest
import json
from datetime import datetime, timedelta, timezone
from sqlalchemy import select, func

from app.notes.models import Note


class TestGetNotes:
    """Test suite for GET /api/notes endpoint."""

    def test_get_notes_requires_authentication(self, client):
        """GET /api/notes without token should return 401."""
        response = client.get('/api/notes')

        assert response.status_code == 401
        data = json.loads(response.data)
        assert data['error']['code'] == 'AUTH_MISSING_TOKEN'

    def test_get_notes_with_invalid_token(self, client):
        """GET /api/notes with invalid token should return 401."""
        headers = {
            'Authorization': 'Bearer invalid-token-12345',
            'Content-Type': 'application/json'
        }
        response = client.get('/api/notes', headers=headers)

        assert response.status_code == 401

    def test_get_notes_with_expired_token(self, client, expired_token):
        """GET /api/notes with expired token should return 401."""
        headers = {
            'Authorization': f'Bearer {expired_token}',
            'Content-Type': 'application/json'
        }
        response = client.get('/api/notes', headers=headers)

        assert response.status_code == 401
        data = json.loads(response.data)
        assert data['error']['code'] == 'AUTH_TOKEN_EXPIRED'

    def test_get_notes_empty_list(self, client, auth_headers, sample_user):
        """GET /api/notes should return empty list when user has no notes."""
        response = client.get('/api/notes', headers=auth_headers)

        assert response.status_code == 200
        data = json.loads(response.data)
        assert data == {'notes': [], 'next_cursor': None}

    def test_get_notes_returns_user_notes(self, client, auth_headers, sample_notes):
        """GET /api/notes should return all notes for authenticated user."""
        response = client.get('/api/notes', headers=auth_headers)

        assert response.status_code == 200
        data = json.loads(response.data)['notes']
        assert len(data) == 3

        for note in data:
            assert set(note) == {'id', 'content', 'created_at'}

    def test_get_notes_returns_only_user_notes(self, client, auth_headers,
                                               sample_notes, other_user_note):
        """GET /api/notes should only return current user's notes."""
        response = client.get('/api/notes', headers=auth_headers)

        assert response.status_code == 200
        data = json.loads(response.data)['notes']

        # Should have 3 notes from sample_user, not the other_user_note
        assert len(data) == 3

        # Verify none of the notes belong to other user
        note_ids = [note['id'] for note in data]
        assert other_user_note.id not in note_ids

    def test_get_notes_correct_content(self, client, auth_headers, sample_note):
        """GET /api/notes should return correct note content."""
        response = client.get('/api/notes', headers=auth_headers)

        assert response.status_code == 200
        data = json.loads(response.data)['notes']
        assert len(data) == 1

        note = data[0]
        assert note['id'] == sample_note.id
        assert note['content'] == 'This is a test note'

    def test_get_notes_includes_timestamps(self, client, auth_headers, sample_note):
        """GET /api/notes should include properly formatted timestamps."""
        response = client.get('/api/notes', headers=auth_headers)

        assert response.status_code == 200
        data = json.loads(response.data)['notes']

        note = data[0]
        assert 'created_at' in note

        # ISO 8601 with the zone stated: without one, browsers read it as
        # their local time
        assert datetime.fromisoformat(note['created_at']).utcoffset() == timedelta(0)


class TestNotesPagination:
    """GET /api/notes pages newest first with a cursor"""

    @pytest.fixture
    def five_notes(self, db, sample_user):
        notes = [Note(user_id=sample_user.id, content=f'Note {i}') for i in range(5)]
        db.session.add_all(notes)
        db.session.commit()
        return [note.id for note in notes]

    def get_page(self, client, auth_headers, query=''):
        response = client.get(f'/api/notes{query}', headers=auth_headers)
        assert response.status_code == 200
        return response.get_json()

    def test_newest_first(self, client, auth_headers, five_notes):
        page = self.get_page(client, auth_headers)

        assert [n['id'] for n in page['notes']] == five_notes[::-1]
        assert page['next_cursor'] is None

    def test_cursor_walks_every_note_exactly_once(
            self, client, auth_headers, five_notes):
        first = self.get_page(client, auth_headers, '?limit=2')
        second = self.get_page(
            client, auth_headers, f"?limit=2&before={first['next_cursor']}")
        third = self.get_page(
            client, auth_headers, f"?limit=2&before={second['next_cursor']}")

        ids = [n['id'] for page in (first, second, third) for n in page['notes']]
        assert ids == five_notes[::-1]
        assert third['next_cursor'] is None

    def test_notes_added_between_pages_do_not_shift_later_pages(
            self, client, auth_headers, five_notes, db, sample_user):
        first = self.get_page(client, auth_headers, '?limit=2')
        db.session.add(Note(user_id=sample_user.id, content='Newer'))
        db.session.commit()

        second = self.get_page(
            client, auth_headers, f"?limit=2&before={first['next_cursor']}")

        assert [n['id'] for n in second['notes']] == five_notes[2:0:-1]

    def test_exact_page_has_no_next_cursor(self, client, auth_headers, five_notes):
        assert self.get_page(client, auth_headers, '?limit=5')['next_cursor'] is None

    def test_default_page_size(self, client, auth_headers, db, sample_user):
        db.session.add_all(
            [Note(user_id=sample_user.id, content='n') for _ in range(25)])
        db.session.commit()

        page = self.get_page(client, auth_headers)

        assert len(page['notes']) == 20
        assert page['next_cursor'] is not None

    def test_cursor_does_not_leak_other_users_notes(
            self, client, auth_headers, five_notes, other_user_note):
        page = self.get_page(client, auth_headers, f'?before={other_user_note.id + 1}')

        assert other_user_note.id not in [n['id'] for n in page['notes']]

    @pytest.mark.parametrize('query', [
        '?limit=0', '?limit=101', '?limit=abc', '?before=0', '?before=x',
        # Past the largest INT id (ID_MAX); 19 nines is past SQLite's 2**63 too
        f'?before={2**31}', f'?before={"9" * 19}',
        # Unknown keys, a typo or a guess at someone else's notes
        '?befor=5', '?user_id=1'])
    def test_invalid_query_is_validation_error(self, client, auth_headers, query):
        response = client.get(f'/api/notes{query}', headers=auth_headers)

        assert response.status_code == 422
        assert response.get_json()['error']['code'] == 'VALIDATION_ERROR'


class TestCreateNote:
    """Test suite for POST /api/notes endpoint."""

    def test_create_note_requires_authentication(self, client):
        """POST /api/notes without token should return 401."""
        payload = {'content': 'Test note'}
        response = client.post(
            '/api/notes',
            data=json.dumps(payload),
            content_type='application/json'
        )

        assert response.status_code == 401
        data = json.loads(response.data)
        assert data['error']['code'] == 'AUTH_MISSING_TOKEN'

    def test_create_note_success(self, client, auth_headers, sample_user):
        """POST /api/notes with valid data should create note and return 201."""
        payload = {'content': 'My new note'}

        response = client.post(
            '/api/notes',
            data=json.dumps(payload),
            headers=auth_headers
        )

        assert response.status_code == 201
        data = json.loads(response.data)

        assert data['content'] == 'My new note'
        assert set(data) == {'id', 'content', 'created_at'}

    def test_create_note_persists_to_database(self, client, auth_headers,
                                              sample_user, db):
        """POST /api/notes should persist note to database."""
        initial_count = db.session.scalar(
            select(func.count()).select_from(Note)
        )

        payload = {'content': 'Persisted note'}
        response = client.post(
            '/api/notes',
            data=json.dumps(payload),
            headers=auth_headers
        )

        assert response.status_code == 201

        new_count = db.session.scalar(
            select(func.count()).select_from(Note)
        )
        assert new_count == initial_count + 1

        note = db.session.execute(
            select(Note).where(Note.content == 'Persisted note')
        ).scalar_one_or_none()

        assert note is not None
        assert note.user_id == sample_user.id

    @pytest.mark.parametrize('payload', [
        {}, {'content': ''}, {'content': '   '}, {'content': 'x' * 257},
        {'content': 'Valid content', 'extra_field': 'should be rejected'},
    ])
    def test_invalid_body_is_validation_error_and_stores_nothing(
            self, client, auth_headers, db, payload):
        response = client.post('/api/notes', json=payload, headers=auth_headers)

        assert response.status_code == 422
        assert response.get_json()['error']['code'] == 'VALIDATION_ERROR'
        assert db.session.scalar(select(func.count()).select_from(Note)) == 0

    def test_create_note_max_length_content(self, client, auth_headers):
        """POST /api/notes with exactly 256 chars should succeed."""
        payload = {'content': 'x' * 256}

        response = client.post(
            '/api/notes',
            data=json.dumps(payload),
            headers=auth_headers
        )

        assert response.status_code == 201
        data = json.loads(response.data)
        assert len(data['content']) == 256

    def test_create_note_invalid_json(self, client, auth_headers, db):
        """A body that is not JSON at all is malformed: 400, not 422"""
        response = client.post(
            '/api/notes',
            data='not valid json{',
            headers=auth_headers
        )

        assert response.status_code == 400
        assert response.get_json()['error']['code'] == 'BAD_REQUEST'
        assert db.session.scalar(select(func.count()).select_from(Note)) == 0

    def test_create_note_wrong_content_type(self, client, auth_token):
        """POST /api/notes with wrong content-type should handle gracefully."""
        headers = {
            'Authorization': f'Bearer {auth_token}',
            'Content-Type': 'text/plain'
        }

        response = client.post(
            '/api/notes',
            data='content=test',
            headers=headers
        )

        assert response.status_code == 415
        assert response.get_json()['error']['code'] == 'UNSUPPORTED_MEDIA_TYPE'

    def test_create_multiple_notes(self, client, auth_headers, sample_user):
        """User should be able to create multiple notes."""
        notes_content = ['First note', 'Second note', 'Third note']

        for content in notes_content:
            payload = {'content': content}
            response = client.post(
                '/api/notes',
                data=json.dumps(payload),
                headers=auth_headers
            )
            assert response.status_code == 201

        response = client.get('/api/notes', headers=auth_headers)
        data = json.loads(response.data)['notes']
        assert len(data) == 3

    def test_create_note_sets_timestamp(self, client, auth_headers):
        """Created note should have timestamp set."""
        payload = {'content': 'Timestamped note'}

        before = datetime.now(timezone.utc).replace(microsecond=0)
        response = client.post(
            '/api/notes',
            data=json.dumps(payload),
            headers=auth_headers
        )
        after = datetime.now(timezone.utc).replace(microsecond=0)

        assert response.status_code == 201
        data = json.loads(response.data)

        # UTC with the zone stated: without one, browsers read it as local time
        created_at = datetime.fromisoformat(data['created_at'])
        assert created_at.utcoffset() == timedelta(0)

        assert before <= created_at <= after

    def test_create_note_different_users(self, client, auth_headers,
                                         second_auth_headers, sample_user,
                                         second_user):
        """Different users should create notes independently."""
        # User 1 creates a note
        payload1 = {'content': 'User 1 note'}
        response1 = client.post(
            '/api/notes',
            data=json.dumps(payload1),
            headers=auth_headers
        )
        assert response1.status_code == 201

        # User 2 creates a note
        payload2 = {'content': 'User 2 note'}
        response2 = client.post(
            '/api/notes',
            data=json.dumps(payload2),
            headers=second_auth_headers
        )
        assert response2.status_code == 201

        # Each user should only see their own note
        response1_notes = client.get('/api/notes', headers=auth_headers)
        user1_notes = json.loads(response1_notes.data)['notes']
        assert len(user1_notes) == 1
        assert user1_notes[0]['content'] == 'User 1 note'

        response2_notes = client.get('/api/notes', headers=second_auth_headers)
        user2_notes = json.loads(response2_notes.data)['notes']
        assert len(user2_notes) == 1
        assert user2_notes[0]['content'] == 'User 2 note'


@pytest.mark.usefixtures('notes_one_below_cap')
class TestNotesCap:
    """POST /api/notes refuses a note past NOTES_MAX_PER_USER"""

    def post(self, client, headers, content='One more'):
        return client.post('/api/notes', json={'content': content}, headers=headers)

    def count(self, db, user):
        return db.session.scalar(
            select(func.count()).select_from(Note).where(Note.user_id == user.id))

    def test_the_last_note_fits_and_the_next_is_refused(
            self, client, auth_headers, db, sample_user):
        assert self.post(client, auth_headers).status_code == 201

        response = self.post(client, auth_headers, 'Past the cap')

        assert response.status_code == 409
        assert response.get_json()['error'] == {
            'code': 'QUOTA_EXCEEDED',
            'message': 'You can keep at most 1,000 notes. Delete one to add another.',
        }
        assert self.count(db, sample_user) == 1000

    def test_another_user_is_unaffected(
            self, client, auth_headers, second_auth_headers, db, second_user):
        assert self.post(client, auth_headers).status_code == 201

        assert self.post(client, second_auth_headers).status_code == 201
        assert self.count(db, second_user) == 1

    def test_deleting_a_note_makes_room(self, client, auth_headers, db, sample_user):
        assert self.post(client, auth_headers).status_code == 201
        oldest = db.session.scalar(
            select(func.min(Note.id)).where(Note.user_id == sample_user.id))

        assert client.delete(f'/api/notes/{oldest}', headers=auth_headers).status_code == 204
        assert self.post(client, auth_headers).status_code == 201


class TestUpdateNote:
    """PUT /api/notes/<id> replaces one of the user's own notes' content"""

    def put(self, client, headers, note_id, content):
        return client.put(f'/api/notes/{note_id}', json={'content': content},
                          headers=headers)

    def test_requires_authentication(self, client, sample_note):
        response = client.put(f'/api/notes/{sample_note.id}', json={'content': 'x'})

        assert response.status_code == 401
        assert response.get_json()['error']['code'] == 'AUTH_MISSING_TOKEN'

    def test_updates_content_and_returns_the_note(
            self, client, auth_headers, sample_note):
        response = self.put(client, auth_headers, sample_note.id, '  Edited  ')

        assert response.status_code == 200
        data = response.get_json()
        # Trimmed, like a new note
        assert data['content'] == 'Edited'
        assert data['id'] == sample_note.id
        assert datetime.fromisoformat(data['created_at']).utcoffset() == timedelta(0)

    def test_persists_and_keeps_its_place(
            self, client, auth_headers, sample_notes, db):
        middle = sample_notes[1]

        self.put(client, auth_headers, middle.id, 'Edited')

        db.session.expire_all()
        assert db.session.get(Note, middle.id).content == 'Edited'
        listed = client.get('/api/notes', headers=auth_headers).get_json()['notes']
        assert [n['content'] for n in listed] == ['Third note', 'Edited', 'First note']

    def test_other_users_note_is_not_found_and_unchanged(
            self, client, auth_headers, other_user_note, db):
        response = self.put(client, auth_headers, other_user_note.id, 'Hijacked')

        assert response.status_code == 404
        assert response.get_json()['error']['code'] == 'NOT_FOUND'
        db.session.expire_all()
        assert db.session.get(Note, other_user_note.id).content == 'Note from another user'

    def test_missing_note_is_not_found(self, client, auth_headers, sample_user):
        response = self.put(client, auth_headers, 999, 'Anything')

        assert response.status_code == 404
        assert response.get_json()['error']['code'] == 'NOT_FOUND'

    @pytest.mark.parametrize('payload', [
        {}, {'content': ''}, {'content': '   '}, {'content': 'x' * 257},
        {'content': 'ok', 'user_id': 2},
    ])
    def test_invalid_body_is_validation_error_and_unchanged(
            self, client, auth_headers, sample_note, db, payload):
        response = client.put(f'/api/notes/{sample_note.id}', json=payload,
                              headers=auth_headers)

        assert response.status_code == 422
        assert response.get_json()['error']['code'] == 'VALIDATION_ERROR'
        db.session.expire_all()
        assert db.session.get(Note, sample_note.id).content == 'This is a test note'

    def test_accepts_the_maximum_length(self, client, auth_headers, sample_note):
        response = self.put(client, auth_headers, sample_note.id, 'x' * 256)

        assert response.status_code == 200
        assert response.get_json()['content'] == 'x' * 256


class TestDeleteNote:
    """DELETE /api/notes/<id> removes one of the user's own notes"""

    def test_requires_authentication(self, client, sample_note):
        response = client.delete(f'/api/notes/{sample_note.id}')

        assert response.status_code == 401
        assert response.get_json()['error']['code'] == 'AUTH_MISSING_TOKEN'

    def test_deletes_only_that_note(self, client, auth_headers, sample_notes, db):
        response = client.delete(f'/api/notes/{sample_notes[1].id}', headers=auth_headers)

        assert response.status_code == 204
        assert response.data == b''
        remaining = db.session.scalars(select(Note.content).order_by(Note.id)).all()
        assert remaining == ['First note', 'Third note']

    def test_deleting_twice_is_not_found(self, client, auth_headers, sample_note):
        url = f'/api/notes/{sample_note.id}'
        client.delete(url, headers=auth_headers)

        response = client.delete(url, headers=auth_headers)

        assert response.status_code == 404
        assert response.get_json()['error']['code'] == 'NOT_FOUND'

    def test_other_users_note_is_not_found_and_kept(
            self, client, auth_headers, other_user_note, db):
        response = client.delete(f'/api/notes/{other_user_note.id}', headers=auth_headers)

        assert response.status_code == 404
        assert response.get_json()['error']['code'] == 'NOT_FOUND'
        db.session.expire_all()
        assert db.session.get(Note, other_user_note.id) is not None


class TestNoteIds:
    """The id in /api/notes/<id> is a positive INT, or the route is not found"""

    # 19 nines is past SQLite's 2**63, which would fail the query without
    # get_own_note_or_404's ID_MAX check
    @pytest.mark.parametrize('note_id', ['0', '-1', 'abc', '1.5', str(2**31), '9' * 19])
    @pytest.mark.parametrize('method, body', [('PUT', {'content': 'x'}), ('DELETE', None)])
    def test_out_of_range_id_is_not_found(
            self, client, auth_headers, sample_user, note_id, method, body):
        response = client.open(f'/api/notes/{note_id}', method=method, json=body,
                               headers=auth_headers)

        assert response.status_code == 404
        assert response.get_json()['error']['code'] == 'NOT_FOUND'

    def test_post_to_a_note_is_not_allowed(self, client, auth_headers, sample_note):
        response = client.post(f'/api/notes/{sample_note.id}', json={'content': 'x'},
                               headers=auth_headers)

        assert response.status_code == 405
        assert response.get_json()['error']['code'] == 'METHOD_NOT_ALLOWED'


class TestNotesEdgeCases:
    """Test edge cases and error scenarios."""

    @pytest.mark.parametrize('url, request_kwargs', [
        ('/api/notes', {'method': 'GET'}),
        ('/api/notes', {'method': 'POST', 'json': {'content': 'x'}}),
        ('/api/notes/1', {'method': 'PUT', 'json': {'content': 'x'}}),
        ('/api/notes/1', {'method': 'DELETE'}),
    ])
    def test_deleted_users_access_token_is_rejected(
            self, client, auth_headers, sample_user, db, url, request_kwargs):
        """An access token outlives its account until it expires; every
        protected route must still turn it away"""
        db.session.delete(sample_user)
        db.session.commit()

        response = client.open(url, headers=auth_headers, **request_kwargs)

        assert response.status_code == 401
        assert response.get_json()['error']['code'] == 'AUTH_INVALID_TOKEN'

    def test_create_note_with_special_characters(self, client, auth_headers):
        """POST /api/notes stores plain text: symbols that are not part of a
        real tag survive verbatim rather than being entity-encoded. Escaping
        is the render layer's responsibility, not storage's."""
        payload = {'content': 'Special chars: <>&"\'(){}[]!@#$%^&*'}

        response = client.post(
            '/api/notes',
            data=json.dumps(payload),
            headers=auth_headers
        )

        assert response.status_code == 201
        data = json.loads(response.data)

        # Stored as plain text, not HTML-escaped
        assert '&lt;' not in data['content']
        assert '&amp;' not in data['content']
        assert '<' in data['content']
        assert '&' in data['content']
        # All other symbols survive untouched
        assert '(){}[]!@#$%^' in data['content']

    def test_create_note_safe_symbols_preserved(self, client, auth_headers):
        """Symbols that cannot be parsed as HTML tags pass through exactly."""
        payload = {'content': 'cost: $100 (50% off!) — great #1 @here'}

        response = client.post(
            '/api/notes',
            data=json.dumps(payload),
            headers=auth_headers
        )

        assert response.status_code == 201
        data = json.loads(response.data)
        assert data['content'] == payload['content']

    def test_create_note_with_unicode(self, client, auth_headers):
        """POST /api/notes should handle Unicode characters."""
        payload = {'content': 'Unicode: 你好 مرحبا שלום'}

        response = client.post(
            '/api/notes',
            data=json.dumps(payload),
            headers=auth_headers
        )

        assert response.status_code == 201
        data = json.loads(response.data)
        assert data['content'] == payload['content']

    @pytest.mark.parametrize('content', ['Launch 🚀', 'Line 1\nLine 2'])
    def test_create_note_with_unsupported_characters_rejected(
            self, client, auth_headers, content):
        """Emoji and control characters are a 422, and nothing is stored"""
        response = client.post(
            '/api/notes',
            data=json.dumps({'content': content}),
            headers=auth_headers
        )

        assert response.status_code == 422
        assert response.get_json()['error']['code'] == 'VALIDATION_ERROR'
        assert client.get('/api/notes', headers=auth_headers).get_json()['notes'] == []

    def test_create_note_whitespace_only_rejected(self, client, auth_headers):
        """Whitespace-only content is trimmed to '' and fails min_length."""
        payload = {'content': '   '}

        response = client.post(
            '/api/notes',
            data=json.dumps(payload),
            headers=auth_headers
        )

        assert response.status_code == 422

class TestNotesMarkup:
    """Notes are plain text stored verbatim; React escapes them on output."""

    def test_markup_round_trips_unchanged(self, client, auth_headers):
        content = "<script>alert('xss')</script> & <b>bold</b>"

        created = client.post(
            '/api/notes', data=json.dumps({'content': content}), headers=auth_headers)
        listed = client.get('/api/notes', headers=auth_headers)

        assert created.status_code == 201
        assert created.get_json()['content'] == content
        assert listed.get_json()['notes'][0]['content'] == content

    def test_responses_are_json_not_html(self, client, auth_headers):
        """A browser must never sniff note content as a page"""
        client.post('/api/notes', data=json.dumps({'content': '<b>x</b>'}),
                    headers=auth_headers)

        response = client.get('/api/notes', headers=auth_headers)

        assert response.mimetype == 'application/json'


class TestDeletingTheAccount:
    def test_deletes_the_users_notes_and_no_one_elses(
            self, client, db, auth_headers, sample_notes, other_user_note):
        response = client.post('/api/account/delete', headers=auth_headers,
                               json={'password': 'TestPassword123'})

        assert response.status_code == 200
        remaining = db.session.execute(select(Note.id)).scalars().all()
        assert remaining == [other_user_note.id]
