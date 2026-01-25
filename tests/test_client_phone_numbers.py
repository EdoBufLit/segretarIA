from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from app import app
from db import Base, get_db
from models import User, AgentRouting, PhoneNumber, Agent
import pytest

# Setup temporary DB
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
def test_client():
    Base.metadata.create_all(bind=engine)
    client = TestClient(app)
    yield client
    Base.metadata.drop_all(bind=engine)

def test_get_client_phone_numbers(test_client):
    # 1. Create User
    db = TestingSessionLocal()
    user = User(username="testuser", email="test@example.com", password_hash="hash")
    db.add(user)
    db.commit()
    db.refresh(user)

    # 2. Login (mock session or bypass auth)
    # Since we use SessionMiddleware, we can't easily mock session in TestClient without a trick
    # or we can use dependency override for get_current_user.

    # Let's override get_current_user for this test
    from auth import get_current_user
    app.dependency_overrides[get_current_user] = lambda: user

    # 3. Call endpoint (Empty)
    response = test_client.get("/api/client/phone-numbers")
    assert response.status_code == 200
    assert response.json()["items"] == []

    # 4. Add Routing
    phone = PhoneNumber(e164="+1234567890", user_id=user.id)
    agent = Agent(agent_id="agent_123", display_name="Test Agent")
    db.add(phone)
    db.add(agent)
    db.commit()

    routing = AgentRouting(user_id=user.id, agent_id="agent_123", phone_number_id=phone.id, is_active=True)
    db.add(routing)
    db.commit()

    # 5. Call endpoint (Populated)
    response = test_client.get("/api/client/phone-numbers")
    assert response.status_code == 200
    items = response.json()["items"]
    assert len(items) == 1
    assert items[0]["phone_number"] == "+1234567890"
    assert items[0]["agent_id"] == "agent_123"

    db.close()
