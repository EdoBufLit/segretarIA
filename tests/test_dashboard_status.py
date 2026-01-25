import pytest
from fastapi.testclient import TestClient
from unittest.mock import MagicMock
from app import app, get_current_user_page, get_db
from models import User, Subscription, Plan, UsageEvent
from datetime import datetime
from sqlalchemy import func

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
    sub.id = 1
    sub.state = state
    sub.plan = MagicMock(spec=Plan)
    sub.plan.code = plan_code
    sub.plan.minutes_per_cycle = 1000
    sub.cycle_start = datetime.utcnow()
    sub.cycle_end = datetime.utcnow()
    sub.updated_at = datetime.utcnow()
    return sub

def test_dashboard_status_active():
    user = create_mock_user(is_active=True)
    sub = create_mock_subscription(state="active")

    mock_db = MagicMock()
    query_mock = mock_db.query.return_value

    # FLUENT INTERFACE MOCK
    # When .filter() is called, return the same query_mock object
    query_mock.filter.return_value = query_mock
    query_mock.order_by.return_value = query_mock

    # Set return values for terminal methods
    query_mock.first.return_value = sub
    query_mock.scalar.return_value = 0 # 0 seconds used

    app.dependency_overrides[get_current_user_page] = lambda: user
    app.dependency_overrides[get_db] = lambda: mock_db

    try:
        response = client.get("/dashboard")
    finally:
        app.dependency_overrides.clear()
    assert response.status_code == 200
    # Check for the Green ATTIVO badge
    assert 'Servizio Attivo' in response.text
    assert 'Servizio Sospeso' not in response.text

def test_dashboard_status_no_sub():
    user = create_mock_user(is_active=True)

    mock_db = MagicMock()
    query_mock = mock_db.query.return_value

    query_mock.filter.return_value = query_mock
    query_mock.order_by.return_value = query_mock

    # First query returns None
    query_mock.first.return_value = None

    app.dependency_overrides[get_current_user_page] = lambda: user
    app.dependency_overrides[get_db] = lambda: mock_db

    try:
        response = client.get("/dashboard")
    finally:
        app.dependency_overrides.clear()
    assert response.status_code == 200
    assert 'Servizio Sospeso' in response.text

def test_dashboard_status_suspended():
    user = create_mock_user(is_active=False)
    sub = create_mock_subscription(state="active")

    mock_db = MagicMock()
    query_mock = mock_db.query.return_value

    query_mock.filter.return_value = query_mock
    query_mock.order_by.return_value = query_mock

    query_mock.first.return_value = sub
    query_mock.scalar.return_value = 0

    app.dependency_overrides[get_current_user_page] = lambda: user
    app.dependency_overrides[get_db] = lambda: mock_db

    try:
        response = client.get("/dashboard")
    finally:
        app.dependency_overrides.clear()
    assert response.status_code == 200
    assert 'Servizio Sospeso' in response.text
