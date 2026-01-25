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

    # We need to handle multiple queries
    # 1. db.query(Subscription) -> ... -> first()
    # 2. db.query(func.sum) -> ... -> scalar()

    def query_side_effect(*args):
        if args[0] == Subscription:
            # Return mock that behaves like the subscription query
            q = MagicMock()
            q.filter.return_value.first.return_value = sub
            return q
        elif str(args[0]) == str(func.sum(UsageEvent.billed_seconds)):
             # Return mock that behaves like the usage query
             q = MagicMock()
             q.filter.return_value.scalar.return_value = 0 # 0 seconds used
             return q
        else:
             return MagicMock()

    # Since comparing func.sum objects is hard, let's just make the mock return a flexible object
    # that can handle both chains.

    # Simpler approach: Make the default return value handle both chains loosely.
    # The subscription chain ends in .first()
    # The usage chain ends in .scalar()

    query_mock = mock_db.query.return_value
    query_mock.filter.return_value.first.return_value = sub
    query_mock.filter.return_value.order_by.return_value.first.return_value = sub
    query_mock.filter.return_value.scalar.return_value = 0

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
    # First query returns None
    query_mock.filter.return_value.first.return_value = None
    # Second query (fallback) also returns None
    query_mock.filter.return_value.order_by.return_value.first.return_value = None

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
    query_mock.filter.return_value.first.return_value = sub
    # Usage query
    query_mock.filter.return_value.scalar.return_value = 0

    app.dependency_overrides[get_current_user_page] = lambda: user
    app.dependency_overrides[get_db] = lambda: mock_db

    response = client.get("/dashboard")
    assert response.status_code == 200
    assert '>SOSPESO</span>' in response.text
