from datetime import datetime, timedelta
from unittest.mock import patch
from auth import generate_reset_token, verify_reset_token, hash_password
from app import app
from fastapi.testclient import TestClient
from db import SessionLocal
from models import User, PasswordResetToken

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
def test_forgot_password_flow(mock_send_email):
    email = "test@example.com"

    with SessionLocal() as db:
        user = db.query(User).filter(User.email == email).first()
        if not user:
            user = User(
                username="testuser",
                email=email,
                password_hash=hash_password("password"),
                role="client",
                is_active=True,
            )
            db.add(user)
            db.commit()
            db.refresh(user)

    response = client.post("/forgot-password", data={"email": email})

    assert response.status_code == 200
    assert "Se l&#39;email esiste" in response.text or "Se l'email esiste" in response.text

    mock_send_email.assert_called_once()
    args, kwargs = mock_send_email.call_args
    assert args[0] == email
    assert args[1] == "Reimposta la tua password"

    with SessionLocal() as db:
        saved = db.query(PasswordResetToken).filter(PasswordResetToken.user_id == user.id).first()
        assert saved is not None
        assert saved.used_at is None
        assert saved.expires_at is not None
        assert saved.token_hash is not None

def test_reset_password_page_valid_token():
    email = "reset_valid@example.com"
    raw_token = "raw-reset-token"

    with SessionLocal() as db:
        user = db.query(User).filter(User.email == email).first()
        if not user:
            user = User(
                username="reset_valid_user",
                email=email,
                password_hash=hash_password("password"),
                role="client",
                is_active=True,
            )
            db.add(user)
            db.commit()
            db.refresh(user)

        db_token = PasswordResetToken(
            user_id=user.id,
            token_hash=hash_password(raw_token),
            expires_at=datetime.utcnow() + timedelta(minutes=30),
        )
        db.add(db_token)
        db.commit()
        user_id = user.id

    response = client.get(f"/reset-password?token={raw_token}&uid={user_id}")
    assert response.status_code == 200
    assert "Nuova Password" in response.text
    assert email in response.text

def test_reset_password_page_invalid_token():
    email = "reset_invalid@example.com"
    with SessionLocal() as db:
        user = db.query(User).filter(User.email == email).first()
        if not user:
            user = User(
                username="reset_invalid_user",
                email=email,
                password_hash=hash_password("password"),
                role="client",
                is_active=True,
            )
            db.add(user)
            db.commit()
            db.refresh(user)

    response = client.get(f"/reset-password?token=invalid_token&uid={user.id}")
    assert response.status_code == 200
    assert "Link scaduto o non valido" in response.text
