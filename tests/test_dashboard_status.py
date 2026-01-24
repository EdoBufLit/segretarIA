import pytest
from fastapi.testclient import TestClient
from unittest.mock import MagicMock
from app import app, get_current_user_page, get_db
from models import User, Subscription, Plan
from datetime import datetime

client = TestClient(app)

# Helper to create mock user
def create_mock_user(role="client", is_active=True, id=1):
    user = MagicMock(spec=User)
    user.id = id
    user.username = "testuser"
    user.email = "test@example.com"
    user.role = role
    user.studio_name = "Test Studio"
    user.is_active = is_active
    # Mock agents list
    user.agents = []
    return user

# Helper to create mock subscription
def create_mock_subscription(state="active", plan_code="pro"):
    sub = MagicMock(spec=Subscription)
    sub.state = state
    sub.plan = MagicMock(spec=Plan)
    sub.plan.code = plan_code
    sub.cycle_start = datetime.utcnow()
    sub.cycle_end = datetime.utcnow()
    sub.updated_at = datetime.utcnow()
    return sub

def test_dashboard_status_active():
    user = create_mock_user(is_active=True)
    sub = create_mock_subscription(state="active")

    mock_db = MagicMock()
    # Logic in app.py:
    # sub = db.query(Subscription).filter(Subscription.user_id == user.id, Subscription.state == "active").first()

    # We need to setup the chain
    query_mock = mock_db.query.return_value
    filter_mock = query_mock.filter.return_value
    filter_mock.first.return_value = sub

    app.dependency_overrides[get_current_user_page] = lambda: user
    app.dependency_overrides[get_db] = lambda: mock_db

    response = client.get("/dashboard")
    assert response.status_code == 200
    # Check for the Green ATTIVO badge
    assert '>ATTIVO</span>' in response.text
    assert '>NON ATTIVO</span>' not in response.text

def test_dashboard_status_no_sub():
    user = create_mock_user(is_active=True)

    mock_db = MagicMock()
    query_mock = mock_db.query.return_value
    filter_mock = query_mock.filter.return_value
    # First query returns None
    filter_mock.first.return_value = None
    # Second query (fallback) also returns None
    # The chain is db.query().filter().order_by().first()
    order_by_mock = filter_mock.order_by.return_value
    order_by_mock.first.return_value = None

    app.dependency_overrides[get_current_user_page] = lambda: user
    app.dependency_overrides[get_db] = lambda: mock_db

    response = client.get("/dashboard")
    assert response.status_code == 200
    assert '>NON ATTIVO</span>' in response.text

def test_dashboard_status_suspended():
    user = create_mock_user(is_active=False)
    sub = create_mock_subscription(state="active")

    mock_db = MagicMock()
    query_mock = mock_db.query.return_value
    filter_mock = query_mock.filter.return_value
    filter_mock.first.return_value = sub

    app.dependency_overrides[get_current_user_page] = lambda: user
    app.dependency_overrides[get_db] = lambda: mock_db

    response = client.get("/dashboard")
    assert response.status_code == 200
    assert '>SOSPESO</span>' in response.text
