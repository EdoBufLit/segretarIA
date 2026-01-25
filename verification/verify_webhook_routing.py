from fastapi.testclient import TestClient
from sqlalchemy.orm import Session
from app import app
from db import SessionLocal, Base, engine
from models import User, PhoneNumber, AgentRouting
from auth import hash_password
from datetime import datetime
import time

client = TestClient(app)

def get_db_session():
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()

def test_webhook_routing_upsert():
    # Setup
    session = SessionLocal()
    # Ensure clean state for this test agent
    agent_id = "test_webhook_agent_123"
    to_number = "+39000111222"

    session.query(AgentRouting).filter(AgentRouting.agent_id == agent_id).delete()
    session.query(PhoneNumber).filter(PhoneNumber.e164 == to_number).delete()
    session.commit()

    # 1. Send Webhook (New Agent, New Number)
    payload = {
        "type": "post_call_transcription",
        "data": {
            "agent_id": agent_id,
            "metadata": {
                "start_time_unix_secs": time.time(),
                "call_duration_secs": 10,
                "phone_call": {
                    "to_number": to_number,
                    "from_number": "+39333444555",
                    "call_sid": "CA12345"
                }
            }
        }
    }

    # We expect status "ignored" because agent is unknown (enforcement),
    # BUT we expect Routing and Phone to be created BEFORE that check returns.
    resp = client.post("/elevenlabs/webhook", json=payload)
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "ignored"
    assert data["reason"] == "unknown_agent"

    # 2. Verify DB Side Effects
    # Check PhoneNumber
    phone = session.query(PhoneNumber).filter(PhoneNumber.e164 == to_number).first()
    assert phone is not None
    assert phone.provider == "elevenlabs"

    # Check AgentRouting
    routing = session.query(AgentRouting).filter(AgentRouting.agent_id == agent_id).first()
    assert routing is not None
    assert routing.status == "unassigned"
    assert routing.user_id is None
    assert routing.phone_number_id == phone.id

    # 3. Simulate Admin assigning user
    # Create a user first
    user = User(username="assign_test", email="assign@example.com", password_hash="hash", role="client")
    session.add(user)
    session.commit()

    # Admin login
    admin_login = client.post("/login", data={"username": "admin", "password": "password123"}) # Assuming default admin exists
    if admin_login.status_code != 200:
        # Create admin if not exists (might fail if already exists but wrong password in seed)
        # Using a mock admin session or fixture would be better, but assuming admin/password123 from .env default
        pass

    # We can test assignment via API logic (or direct DB update if login fails)
    routing.user_id = user.id
    routing.status = "active"
    session.commit()

    # 4. Send Webhook again (Existing Agent)
    # Now that it's assigned, it might pass "unknown_agent" check if we sync Agent table?
    # Actually, "unknown_agent" check queries `Agent` table, not `AgentRouting`.
    # So it will still fail enforcement unless we also create an Agent row.
    # But let's check if `last_event_at` updates.

    old_last_event = routing.last_event_at
    time.sleep(1)

    resp = client.post("/elevenlabs/webhook", json=payload)

    session.refresh(routing)
    assert routing.last_event_at > old_last_event
    assert routing.user_id == user.id # Should remain assigned

    # Cleanup
    session.delete(routing)
    session.delete(phone)
    session.delete(user)
    session.commit()
    session.close()

if __name__ == "__main__":
    test_webhook_routing_upsert()
    print("Test passed!")
