import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session
from app import app
from db import get_db, Base
from models import User, PhoneNumber, AgentRouting
from auth import hash_password
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

# Setup test DB
SQLALCHEMY_DATABASE_URL = "sqlite:///./test.db"
engine = create_engine(SQLALCHEMY_DATABASE_URL, connect_args={"check_same_thread": False})
TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

def override_get_db():
    try:
        db = TestingSessionLocal()
        yield db
    finally:
        db.close()

app.dependency_overrides[get_db] = override_get_db

@pytest.fixture(scope="module")
def client():
    Base.metadata.create_all(bind=engine)
    with TestClient(app) as c:
        yield c
    Base.metadata.drop_all(bind=engine)

@pytest.fixture(scope="function")
def db_session():
    # Ensure tables exist
    Base.metadata.create_all(bind=engine)
    db = TestingSessionLocal()
    try:
        yield db
    finally:
        db.close()

def create_admin(db):
    admin = db.query(User).filter_by(username="admin_test").first()
    if not admin:
        admin = User(
            username="admin_test",
            email="admin@test.com",
            password_hash=hash_password("admin"),
            role="admin",
            is_active=True
        )
        db.add(admin)
        db.commit()
        db.refresh(admin)
    return admin

def create_client_user(db, username="client_test"):
    user = db.query(User).filter_by(username=username).first()
    if not user:
        user = User(
            username=username,
            email=f"{username}@test.com",
            password_hash=hash_password("client"),
            role="client",
            is_active=True
        )
        db.add(user)
        db.commit()
        db.refresh(user)
    return user

def test_duplicate_phone_number(client, db_session):
    admin = create_admin(db_session)
    user = create_client_user(db_session)

    # Login Admin
    client.post("/login", data={"username": "admin_test", "password": "admin"})

    # Create first time
    resp = client.post("/api/admin/phone-numbers", json={
        "e164": "+1234567890",
        "user_id": user.id,
        "notes": "First"
    })
    assert resp.status_code == 200

    # Create Duplicate
    resp = client.post("/api/admin/phone-numbers", json={
        "e164": "+1234567890",
        "user_id": user.id,
        "notes": "Second"
    })
    assert resp.status_code == 400
    assert "Il numero è già presente" in resp.json()["detail"]

def test_client_dashboard_numbers(client, db_session):
    # Setup: Admin creates number for client
    admin = create_admin(db_session)
    user = create_client_user(db_session, "client_view")

    # Login Admin to create
    client.post("/login", data={"username": "admin_test", "password": "admin"})
    client.post("/api/admin/phone-numbers", json={
        "e164": "+1987654321",
        "user_id": user.id,
        "notes": "For Client"
    })

    # Login Client
    client.post("/login", data={"username": "client_view", "password": "client"})

    # Fetch numbers
    resp = client.get("/api/client/phone-numbers")
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "ok"
    # Find our number
    found = False
    for item in data["items"]:
        if item["phone_number"] == "+1987654321":
            found = True
            assert item["agent_id"] == "Non assegnato"
            break
    assert found

def test_hard_delete(client, db_session):
    admin = create_admin(db_session)
    user = create_client_user(db_session, "user_del")

    # Login Admin
    client.post("/login", data={"username": "admin_test", "password": "admin"})

    # Create number
    resp = client.post("/api/admin/phone-numbers", json={
        "e164": "+111222333",
        "user_id": user.id
    })
    phone_id = resp.json()["id"]

    # Hard Delete
    resp = client.delete(f"/api/admin/phone-numbers/{phone_id}/permanent")
    assert resp.status_code == 200

    # Verify gone
    phone = db_session.query(PhoneNumber).filter_by(id=phone_id).first()
    assert phone is None
