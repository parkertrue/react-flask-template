"""Deleting an account on real MySQL and Redis: the user's row and every
session go, under the app's own database and ACL users."""
from flask_jwt_extended import create_access_token
from sqlalchemy import func, select

from app.auth.models import User

PASSWORD = 'TestPassword123'  # integration_user's


def test_deletes_the_row_and_the_sessions(
        integration_client, integration_db, integration_user, integration_redis):
    user_id = integration_user.id
    for _ in range(2):
        integration_client.post('/api/auth/login', json={
            'email': integration_user.email, 'password': PASSWORD})
    client = integration_redis.get_client()
    assert client.zcard(f'refresh_tokens:{user_id}') == 2

    response = integration_client.post(
        '/api/account/delete', json={'password': PASSWORD},
        headers={'Authorization': f'Bearer {create_access_token(identity=str(user_id))}'})

    assert response.status_code == 200
    assert client.exists(f'refresh_tokens:{user_id}') == 0
    integration_db.session.expire_all()
    assert integration_db.session.scalar(select(func.count()).select_from(User)) == 0
