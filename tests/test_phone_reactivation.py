import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session
from app import app
from db import SessionLocal, Base, engine
from models import User, PhoneNumber
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
    admin = db.query(User).filter(User.username == "admin_react_test").first()
    if not admin:
        admin = User(
            username="admin_react_test",
            email="admin_react@example.com",
            password_hash=hash_password("password"),
            role="admin",
            is_active=True
        )
        db.add(admin)
        db.commit()
    return admin

def create_user(db: Session, username):
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

def create_phone(db: Session, user: User, e164):
    phone = db.query(PhoneNumber).filter(PhoneNumber.e164 == e164).first()
    if not phone:
        phone = PhoneNumber(e164=e164, user_id=user.id, status="active", released_at=None)
        db.add(phone)
        db.commit()
    else:
        phone.status = "active"
        phone.released_at = None
        phone.user_id = user.id
        db.commit()
    return phone

def test_release_and_reactivate(db_session: Session):
    admin = create_admin(db_session)
    user1 = create_user(db_session, "user_react_1")
    user2 = create_user(db_session, "user_react_2")

    phone = create_phone(db_session, user1, "+39000555666")

    # Login
    client.post("/login", data={"username": "admin_react_test", "password": "password"})

    # 1. Release
    resp = client.delete(f"/api/admin/phone-numbers/{phone.id}")
    assert resp.status_code == 200, resp.text

    db_session.refresh(phone)
    assert phone.status == "released"
    assert phone.released_at is not None
    assert phone.user_id is None

    # 2. Reactivate to User 2
    payload = {"user_id": user2.id}
    resp = client.post(f"/api/admin/phone-numbers/{phone.id}/reactivate", json=payload)
    assert resp.status_code == 200, resp.text

    db_session.refresh(phone)
    assert phone.status == "active"
    assert phone.released_at is None
    assert phone.user_id == user2.id

    # Cleanup
    client.delete(f"/api/admin/phone-numbers/{phone.id}/permanent")
