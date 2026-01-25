from fastapi.testclient import TestClient
from unittest.mock import MagicMock
from app import app
from db import get_db
from models import User, PasswordResetToken
from auth import hash_password
from datetime import datetime, timedelta

client = TestClient(app)

def test_reset_password_submit_success():
    # Mock DB
    mock_db = MagicMock()
    mock_user = MagicMock(spec=User)
    mock_user.id = 1
    mock_user.email = "test@example.com"
    mock_user.password_hash = "oldhash"

    mock_token = MagicMock(spec=PasswordResetToken)
    # auth.verify_password verifies against this hash
    mock_token.token_hash = hash_password("validtoken")
    mock_token.used_at = None
    mock_token.expires_at = datetime.utcnow() + timedelta(minutes=30)
    mock_token.user_id = 1

    # Setup queries
    def query_side_effect(model):
        q = MagicMock()
        if model == User:
            q.filter.return_value.first.return_value = mock_user
        elif model == PasswordResetToken:
             # Chain filters: filter(...).filter(...).all()
             # We simplify by returning the token at the end of the chain
             q.filter.return_value.filter.return_value.all.return_value = [mock_token]
             # Fallback for single filter
             q.filter.return_value.all.return_value = [mock_token]
        return q

    mock_db.query.side_effect = query_side_effect

    app.dependency_overrides[get_db] = lambda: mock_db

    response = client.post(
        "/reset-password",
        data={
            "token": "validtoken",
            "uid": "1",
            "password": "newpassword123",
            "password_confirm": "newpassword123"
        },
        follow_redirects=False
    )

    # Clean up
    app.dependency_overrides = {}

    # Should redirect on success
    assert response.status_code == 302
    assert response.headers["location"] == "/login?reset=1"

def test_reset_password_missing_uid_bug_reproduction():
    # This simulates the bug reported by the user (frontend missing uid)
    # Expected: 422 Unprocessable Entity (JSON) with "field required" for uid

    response = client.post(
        "/reset-password",
        data={
            "token": "validtoken",
            # "uid": "1",  <-- MISSING
            "password": "newpassword123",
            "password_confirm": "newpassword123"
        }
    )
    assert response.status_code == 422
    data = response.json()
    # Pydantic v2 might capitalize or not, depending on version. "Field required" is typical.
    assert data["detail"][0]["msg"].lower() == "field required"
    assert "uid" in data["detail"][0]["loc"]

def test_reset_password_validation_error_renders_html():
    # Verify our "Improve Error Handling" fix
    mock_db = MagicMock()
    mock_user = MagicMock(spec=User)
    mock_user.id = 1
    mock_user.email = "test@example.com"

    mock_query = MagicMock()
    mock_db.query.return_value = mock_query
    mock_query.filter.return_value.first.return_value = mock_user

    app.dependency_overrides[get_db] = lambda: mock_db

    response = client.post(
        "/reset-password",
        data={
            "token": "validtoken",
            "uid": "1",
            "password": "short",
            "password_confirm": "short"
        }
    )

    app.dependency_overrides = {}

    assert response.status_code == 200
    assert "text/html" in response.headers["content-type"]
    assert "La password deve essere di almeno 8 caratteri" in response.text
    # Verify email is preserved in context (so {{ email }} works)
    assert "test@example.com" in response.text
