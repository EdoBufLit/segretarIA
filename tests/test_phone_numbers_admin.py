import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session
from app import app
from db import get_db
from models import User, PhoneNumber
from auth import hash_password
from datetime import datetime, timedelta
from db import SessionLocal, Base, engine
from unittest.mock import patch

client = TestClient(app)

@pytest.fixture(scope="module")
def db_session():
    # Setup database (maybe just use the existing one or test db)
    # For simplicity in this environment, we use the existing DB session but rollback transactions or just ensure cleanup.
    # However, SessionLocal() connects to the real DB.
    # Ideally we should use a separate test DB, but for now we proceed with caution and cleanup.

    # Ensure tables exist
    Base.metadata.create_all(bind=engine)

    session = SessionLocal()
    yield session
    session.close()

# Helper to create admin
def create_admin(db: Session):
    admin = db.query(User).filter(User.username == "admin_test").first()
    if not admin:
        admin = User(
            username="admin_test",
            email="admin_test@example.com",
            password_hash=hash_password("password"),
            role="admin",
            is_active=True
        )
        db.add(admin)
        db.commit()
    return admin

# Helper to create client user
def create_client_user(db: Session, username="client_test"):
    user = db.query(User).filter(User.username == username).first()
    if not user:
        user = User(
            username=username,
            email=f"{username}@example.com",
            password_hash=hash_password("password"),
            role="client",
            is_active=True
        )
        db.add(user)
        db.commit()
    return user

def test_admin_phone_numbers_crud(db_session: Session):
    # Setup
    admin = create_admin(db_session)
    user = create_client_user(db_session, "phone_owner")

    with patch("admin_service.send_email"):
        # Login as admin
        login_resp = client.post("/login", data={"username": "admin_test", "password": "password"})
        # TestClient follows redirects by default, so we land on dashboard (200)
        assert login_resp.status_code == 200

        # 1. Create Phone Number via API
        payload = {
            "e164": "+393330000001",
            "user_id": user.id,
            "notes": "Test number"
        }
        resp = client.post("/api/admin/phone-numbers", json=payload)
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ok"
        phone_id = data["id"]

        # Verify DB
        phone = db_session.query(PhoneNumber).filter(PhoneNumber.id == phone_id).first()
        assert phone is not None
        assert phone.e164 == "+393330000001"
        assert phone.user_id == user.id
        assert phone.notes == "Test number"
        assert phone.status == "active"

        # 2. List Phone Numbers
        resp = client.get("/api/admin/phone-numbers")
        assert resp.status_code == 200
        list_data = resp.json()
        items = list_data["items"]
        assert len(items) >= 1
        found = next((i for i in items if i["id"] == phone_id), None)
        assert found is not None
        assert found["e164"] == "+393330000001"
        assert found["username"] == "phone_owner"

        # 3. Update Notes
        resp = client.patch(f"/api/admin/phone-numbers/{phone_id}", json={"notes": "Updated notes"})
        assert resp.status_code == 200
        db_session.refresh(phone)
        assert phone.notes == "Updated notes"

        # 4. Release (Delete logic) -> sets status to released
        resp = client.delete(f"/api/admin/phone-numbers/{phone_id}")
        assert resp.status_code == 200
        db_session.refresh(phone)
        assert phone.status == "released"
        assert phone.released_at is not None

        # 5. Cancel Deprovision (Simulate pending_deprovision first)
        phone.status = "pending_deprovision"
        phone.deprovision_at = datetime.utcnow() + timedelta(days=30)
        db_session.commit()

        resp = client.post(f"/api/admin/phone-numbers/{phone_id}/cancel-deprovision")
        assert resp.status_code == 200
        db_session.refresh(phone)
        assert phone.status == "active"
        assert phone.deprovision_at is None

        # Cleanup
        db_session.delete(phone)
        db_session.delete(user)
        # db_session.delete(admin) # Keep admin for other tests if needed, or delete.
        db_session.commit()

def test_admin_phone_numbers_security(db_session: Session):
    # Setup
    user = create_client_user(db_session, "hacker")

    # Login as client
    client.post("/login", data={"username": "hacker", "password": "password"})

    # Try to access admin API
    resp = client.get("/api/admin/phone-numbers")
    # Should be redirected or 403 depending on implementation.
    # require_role usually raises NotAuthorizedPage which redirects to /dashboard for clients
    # However, for API endpoints we might expect JSON 403?
    # The current app uses `get_current_admin_user` which raises HTTPException(403) for APIs usually,
    # or Redirect if it's a page dependency.
    # Let's check app.py: `admin: User = Depends(get_current_admin_user)`
    # get_current_admin_user raises HTTPException 403.

    assert resp.status_code in [403, 302]
