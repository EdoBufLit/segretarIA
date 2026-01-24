from unittest.mock import MagicMock, patch
from auth import generate_reset_token, verify_reset_token, get_token_serializer
from app import app
from fastapi.testclient import TestClient

client = TestClient(app)

def test_reset_token_flow():
    email = "test@example.com"
    token = generate_reset_token(email)
    assert token is not None

    verified_email = verify_reset_token(token)
    assert verified_email == email

def test_reset_token_expiration():
    email = "test@example.com"
    # The salt is set during loads/dumps, not on the serializer instance itself if default
    token = generate_reset_token(email)
    verified = verify_reset_token(token, expiration=-1) # Force expiration
    assert verified is None

@patch("app.send_email")
@patch("app.SessionLocal") # Mock DB for User query
def test_forgot_password_flow(mock_session, mock_send_email):
    # Mock User
    mock_db = MagicMock()
    mock_user = MagicMock()
    mock_user.email = "test@example.com"
    mock_user.username = "TestUser"

    mock_db.query.return_value.filter.return_value.first.return_value = mock_user

    # We need to override get_db dependency or just rely on app.py logic which uses 'db' dependency
    # The test client uses the app, so we should override_dependency
    from db import get_db
    app.dependency_overrides[get_db] = lambda: mock_db

    response = client.post("/forgot-password", data={"email": "test@example.com"})

    assert response.status_code == 200
    # The message should be in the response, likely inside the HTML div we added
    # "Se l'email esiste, riceverai un link per il reset della password."
    assert "Se l&#39;email esiste" in response.text or "Se l'email esiste" in response.text

    # Verify email sent
    # We used send_email(to, subject, body, from)
    mock_send_email.assert_called_once()
    args, _ = mock_send_email.call_args
    # args: (to, subject, body, from)
    assert args[0] == "test@example.com"
    assert "Reset Password" in args[1]
    assert "/reset-password?token=" in args[2]

def test_reset_password_page_valid_token():
    email = "test@example.com"
    token = generate_reset_token(email)

    response = client.get(f"/reset-password?token={token}")
    assert response.status_code == 200
    assert 'Imposta Nuova Password' in response.text
    assert email in response.text

def test_reset_password_page_invalid_token():
    response = client.get("/reset-password?token=invalid_token")
    assert response.status_code == 200
    assert "Link scaduto o non valido" in response.text
