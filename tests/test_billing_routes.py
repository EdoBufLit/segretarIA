from fastapi.testclient import TestClient
from app import app
from db import SessionLocal, Base, engine
from models import User
from auth import hash_password

client = TestClient(app)

def setup_module(module):
    Base.metadata.create_all(bind=engine)
    db = SessionLocal()
    if not db.query(User).filter_by(username="testclient").first():
        user = User(
            username="testclient",
            email="testclient@example.com",
            password_hash=hash_password("password"),
            role="client",
            is_active=True
        )
        db.add(user)
        db.commit()
    db.close()

def test_plans_page_accessible_unauthenticated():
    response = client.get("/billing/plans")
    assert response.status_code == 200
    assert "Starter" in response.text
    assert "Pro" in response.text
    assert "Business" in response.text

def test_plans_page_accessible_authenticated():
    # Login first
    client.post("/login", data={"username": "testclient", "password": "password"})
    response = client.get("/billing/plans")
    assert response.status_code == 200
    assert "Starter" in response.text
