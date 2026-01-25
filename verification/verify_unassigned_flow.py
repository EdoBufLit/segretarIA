import os
import json
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker
import sys

# Ensure we use the test DB
os.environ["DATABASE_URL"] = "sqlite:///./test.db"

# Add parent dir to path to import app
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import app
from db import Base
from models import UnassignedEvent, User

# Create client
client = TestClient(app)

def test_unassigned_flow():
    # 1. Clean DB (Unassigned Events)
    engine = create_engine(os.environ["DATABASE_URL"])
    with engine.connect() as conn:
        conn.execute(text("DELETE FROM unassigned_events"))
        conn.commit()

    # 2. Send Webhook with unknown agent
    payload = {
        "type": "post_call_transcription",
        "data": {
            "agent_id": "unknown_agent_xyz",
            "metadata": {
                "phone_call": {
                    "number": "+1234567890",
                    "call_sid": "call_123"
                },
                "call_duration_secs": 10
            }
        }
    }

    response = client.post("/elevenlabs/webhook", json=payload)

    print(f"Webhook Response: {response.status_code} {response.json()}")
    assert response.status_code == 200
    assert response.json()["message"] == "Event stored as unassigned"

    # 3. Verify DB
    Session = sessionmaker(bind=engine)
    session = Session()
    event = session.query(UnassignedEvent).filter_by(agent_id="unknown_agent_xyz").first()
    assert event is not None
    assert event.phone_number == "+1234567890"
    print("DB Verification Passed: Event found in unassigned_events table.")

    # 4. Verify Admin Endpoint
    # Need to be admin. We can mock dependency or just create an admin user in DB.
    # Let's create a temp admin user.
    admin_user = session.query(User).filter_by(username="temp_admin").first()
    if not admin_user:
        from auth import hash_password
        admin_user = User(
            username="temp_admin",
            email="admin@test.com",
            password_hash=hash_password("password"),
            role="admin",
            is_active=True
        )
        session.add(admin_user)
        session.commit()

    # Login to get session
    login_resp = client.post("/login", data={"username": "temp_admin", "password": "password"}, follow_redirects=False)
    assert login_resp.status_code == 302 # Redirect on success

    # Call endpoint
    admin_resp = client.get("/api/admin/unassigned-events")
    print(f"Admin Endpoint Response: {admin_resp.status_code}")
    if admin_resp.status_code != 200:
        print(admin_resp.json())

    assert admin_resp.status_code == 200
    data = admin_resp.json()
    assert data["total"] >= 1
    found = False
    for item in data["items"]:
        if item["agent_id"] == "unknown_agent_xyz":
            found = True
            break
    assert found
    print("Admin Endpoint Verification Passed.")

if __name__ == "__main__":
    try:
        test_unassigned_flow()
        print("\nSUCCESS: Unassigned flow verified.")
    except Exception as e:
        print(f"\nFAILURE: {e}")
        import traceback
        traceback.print_exc()
        exit(1)
