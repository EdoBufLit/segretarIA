import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session
from app import app
from db import SessionLocal, Base, engine
from models import User, PhoneNumber, AgentRouting
from auth import hash_password
from datetime import datetime

client = TestClient(app)

@pytest.fixture(scope="module")
def db_session():
    # Setup
    Base.metadata.create_all(bind=engine)
    session = SessionLocal()
    yield session
    session.close()

def create_admin(db: Session):
    admin = db.query(User).filter(User.username == "admin_routing_test").first()
    if not admin:
        admin = User(
            username="admin_routing_test",
            email="admin_routing@example.com",
            password_hash=hash_password("password"),
            role="admin",
            is_active=True
        )
        db.add(admin)
        db.commit()
    return admin

def create_client_user(db: Session, username="client_routing"):
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

def create_phone(db: Session, user: User, e164="+390000000000"):
    phone = db.query(PhoneNumber).filter(PhoneNumber.e164 == e164).first()
    if not phone:
        phone = PhoneNumber(e164=e164, user_id=user.id, status="active")
        db.add(phone)
        db.commit()
    return phone

def test_admin_routing_crud(db_session: Session):
    # Setup
    admin = create_admin(db_session)
    user = create_client_user(db_session)
    phone = create_phone(db_session, user, "+39999888777")

    # Login as admin
    login_resp = client.post("/login", data={"username": "admin_routing_test", "password": "password"})
    assert login_resp.status_code == 200

    # 1. Create Routing
    payload = {
        "user_id": user.id,
        "agent_id": "eleven_agent_123",
        "phone_number_id": phone.id,
        "is_active": True
    }
    resp = client.post("/api/admin/routing", json=payload)
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "ok"
    routing_id = data["id"]

    # Verify DB
    r = db_session.query(AgentRouting).filter(AgentRouting.id == routing_id).first()
    assert r.agent_id == "eleven_agent_123"
    assert r.user_id == user.id
    assert r.is_active is True

    # 2. List Routing
    resp = client.get("/api/admin/routing")
    assert resp.status_code == 200
    data = resp.json()
    items = data["items"]
    found = next((i for i in items if i["id"] == routing_id), None)
    assert found is not None
    assert found["agent_id"] == "eleven_agent_123"
    assert found["e164"] == "+39999888777"

    # 3. Update Routing
    resp = client.patch(f"/api/admin/routing/{routing_id}", json={"agent_id": "eleven_agent_456", "is_active": False})
    assert resp.status_code == 200
    db_session.refresh(r)
    assert r.agent_id == "eleven_agent_456"
    assert r.is_active is False

    # 4. Delete Routing
    resp = client.delete(f"/api/admin/routing/{routing_id}")
    assert resp.status_code == 200
    r = db_session.query(AgentRouting).filter(AgentRouting.id == routing_id).first()
    assert r is None

    # Cleanup
    db_session.delete(phone)
    db_session.delete(user)
    # db_session.delete(admin)
    db_session.commit()
