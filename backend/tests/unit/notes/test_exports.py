"""The user's notes in their data export (GET /api/account/export)"""


def test_holds_the_users_notes_oldest_first(
        client, sample_user, sample_notes, other_user_note, auth_headers):
    response = client.get('/api/account/export', headers=auth_headers)

    assert response.get_json()['data']['notes'] == [
        {'id': note.id, 'content': note.content,
         'created_at': note.created_at.isoformat() + '+00:00'}
        for note in sample_notes
    ]


def test_leaves_out_other_users_notes(client, sample_user, other_user_note, auth_headers):
    response = client.get('/api/account/export', headers=auth_headers)

    assert response.get_json()['data']['notes'] == []
