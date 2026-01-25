from unittest.mock import MagicMock, patch, ANY
from app import app
from fastapi.testclient import TestClient
from models import User, PasswordResetToken
from datetime import datetime, timedelta
import secrets

client = TestClient(app)

# Helper to create mock user
def create_mock_user(id=1, email="test@example.com", username="TestUser"):
    user = MagicMock(spec=User)
    user.id = id
    user.email = email
    user.username = username
    return user

@patch("app.send_email")
def test_forgot_password_flow(mock_send_email):
    # Mock DB
    mock_db = MagicMock()
    mock_user = create_mock_user()

    # query(User).filter(...).first() returns mock_user
    mock_db.query.return_value.filter.return_value.first.return_value = mock_user

    # Override dependency
    from db import get_db
    app.dependency_overrides[get_db] = lambda: mock_db

    try:
        response = client.post("/forgot-password", data={"email": "test@example.com"})
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    # Check for success message
    assert "Se l&#39;email esiste" in response.text or "Se l'email esiste" in response.text

    # Verify email sent
    mock_send_email.assert_called_once()
    args, _ = mock_send_email.call_args
    # args: (to, subject, body, html_body) - wait, app.py calls send_email(user.email, subject, "Please view in HTML", html_body=body)

    assert args[0] == "test@example.com"
    assert "Reimposta la tua password" in args[1]

    html_body = _[ 'html_body'] if 'html_body' in _ else args[3]
    assert "/reset-password?token=" in html_body
    assert f"uid={mock_user.id}" in html_body

    # Verify token saved to DB
    # db.add(db_token)
    mock_db.add.assert_called_once()
    added_obj = mock_db.add.call_args[0][0]
    assert isinstance(added_obj, PasswordResetToken)
    assert added_obj.user_id == mock_user.id


def test_reset_password_page_valid_token():
    mock_db = MagicMock()
    mock_user = create_mock_user()

    token_raw = "valid-token"
    # We need a token that verifies.
    # In app.py: verify_password(token, t.token_hash)
    # mocking verify_password is hard without patching it.

    # Let's mock the DB query for User and Token

    # 1. User query
    # user = db.query(User).filter(User.id == uid).first()

    # 2. Token query
    # tokens = db.query(PasswordResetToken).filter(...).all()

    # We need to distinguish queries.
    # MagicMock chaining is tricky for multiple distinct queries on same session.
    # usually query(Model) returns a query object specific to that model.

    # Let's patch get_db
    from db import get_db
    app.dependency_overrides[get_db] = lambda: mock_db

    # When app queries User, return mock_user
    # When app queries PasswordResetToken, return [mock_token]

    mock_token = MagicMock(spec=PasswordResetToken)
    mock_token.token_hash = "hashed_secret"

    def side_effect(model):
        if model == User:
            q = MagicMock()
            q.filter.return_value = q
            q.first.return_value = mock_user
            return q
        if model == PasswordResetToken:
            q = MagicMock()
            q.filter.return_value = q
            q.all.return_value = [mock_token]
            return q
        return MagicMock()

    mock_db.query.side_effect = side_effect

    # We also need to patch verify_password to return True
    with patch("app.verify_password", return_value=True):
        try:
            response = client.get(f"/reset-password?token={token_raw}&uid={mock_user.id}")
        finally:
            app.dependency_overrides.clear()

    assert response.status_code == 200
    assert 'Nuova Password' in response.text # Title of the page or form header
    assert mock_user.email in response.text


def test_reset_password_page_invalid_token():
    mock_db = MagicMock()
    mock_user = create_mock_user()

    # Case: User found, but no valid token
    def side_effect(model):
        if model == User:
            q = MagicMock()
            q.filter.return_value = q
            q.first.return_value = mock_user
            return q
        if model == PasswordResetToken:
            q = MagicMock()
            # Return empty list or tokens that fail verification
            q.filter.return_value = q
            q.all.return_value = []
            return q
        return MagicMock()

    mock_db.query.side_effect = side_effect

    from db import get_db
    app.dependency_overrides[get_db] = lambda: mock_db

    try:
        response = client.get(f"/reset-password?token=invalid&uid={mock_user.id}")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    assert "Link scaduto o non valido" in response.text
