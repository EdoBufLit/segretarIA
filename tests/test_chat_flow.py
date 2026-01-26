import pytest
from fastapi.testclient import TestClient
from unittest.mock import patch, MagicMock
from app import app
from models import User, ChatMessage
from auth import hash_password
from db import SessionLocal
import json

client = TestClient(app)

@pytest.fixture
def mock_alerting():
    with patch("app.notify_chat_message") as mock_notify:
        yield mock_notify

@pytest.fixture(autouse=True)
def cleanup_chat():
    # Setup: clean chat messages
    with SessionLocal() as db:
        db.query(ChatMessage).delete()
        db.commit()
    yield
    # Teardown
    with SessionLocal() as db:
        db.query(ChatMessage).delete()
        db.commit()

def test_chat_flow(mock_alerting):
    # 1. Register Client
    client_username = "chat_client_test"
    client_email = "chat_client@test.com"

    # Clean user if exists from prev run
    with SessionLocal() as db:
        u = db.query(User).filter(User.username == client_username).first()
        if u:
            # Delete constraints if needed, but cascade might not be set
            db.query(ChatMessage).filter(ChatMessage.user_id == u.id).delete()
            db.delete(u)
            db.commit()

    client.post("/register", data={
        "username": client_username,
        "email": client_email,
        "password": "password123",
        "password_confirm": "password123"
    })

    # Login Client
    resp = client.post("/login", data={"username": client_username, "password": "password123"}, follow_redirects=False)
    client_cookie = resp.cookies

    # Get Client ID
    resp = client.get("/me", cookies=client_cookie)
    client_id = resp.json()["user"]["id"]

    # 2. Register Admin
    with SessionLocal() as db:
        admin = db.query(User).filter(User.username == "admin_chat_test").first()
        if not admin:
            admin = User(username="admin_chat_test", email="admin_chat@test.com", password_hash=hash_password("password"), role="admin", is_active=True)
            db.add(admin)
            db.commit()
        admin_id = admin.id

    # Login Admin
    resp = client.post("/login", data={"username": "admin_chat_test", "password": "password"}, follow_redirects=False)
    admin_cookie = resp.cookies

    # 3. Client Sends Message
    msg_content = "Hello Admin, help please!"
    resp = client.post("/api/chat/messages",
                       json={"message": msg_content},
                       cookies=client_cookie)
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"

    # Verify Telegram Alert Mock
    mock_alerting.assert_called_once()
    args, _ = mock_alerting.call_args
    assert args[0].id == client_id
    assert args[1] == msg_content

    # 4. Admin gets conversations
    resp = client.get("/api/admin/chat/conversations", cookies=admin_cookie)
    assert resp.status_code == 200
    data = resp.json()
    assert len(data["conversations"]) >= 1
    # Find our client
    conv = next((c for c in data["conversations"] if c["user_id"] == client_id), None)
    assert conv is not None
    assert conv["unread_count"] > 0
    assert conv["last_message"] == msg_content

    # 5. Admin reads messages (fetch detail)
    resp = client.get(f"/api/chat/messages?limit=100&user_id={client_id}", cookies=admin_cookie)
    assert resp.status_code == 200
    msgs = resp.json()["items"]
    assert len(msgs) == 1
    assert msgs[0]["message"] == msg_content
    assert msgs[0]["sender"] == "client"

    resp = client.post("/api/chat/read", json={"user_id": client_id}, cookies=admin_cookie)
    assert resp.status_code == 200

    # Verify unread count is now 0
    resp = client.get("/api/admin/chat/conversations", cookies=admin_cookie)
    conv = next((c for c in resp.json()["conversations"] if c["user_id"] == client_id), None)
    assert conv["unread_count"] == 0

    # 6. Admin replies
    reply_content = "Hello Client, how can I help?"
    resp = client.post("/api/chat/messages",
                       json={"message": reply_content, "user_id": client_id},
                       cookies=admin_cookie)
    assert resp.status_code == 200

    # 7. Client checks messages
    resp = client.get("/api/chat/messages", cookies=client_cookie)
    msgs = resp.json()["items"]
    assert len(msgs) == 2
    assert msgs[1]["sender"] == "admin"
    assert msgs[1]["message"] == reply_content

    # Client Unread Count
    resp = client.get("/api/chat/unread-count", cookies=client_cookie)
    assert resp.json()["count"] == 1

    # Client marks read
    resp = client.post("/api/chat/read", json={}, cookies=client_cookie)
    assert resp.status_code == 200

    resp = client.get("/api/chat/unread-count", cookies=client_cookie)
    assert resp.json()["count"] == 0
