import pytest
from unittest.mock import MagicMock
from fastapi.testclient import TestClient
from app import app, get_db
from models import PhoneNumber, User, AgentRouting

client = TestClient(app)

@pytest.fixture
def mock_db_session():
    mock_session = MagicMock()
    return mock_session

@pytest.fixture
def override_get_db(mock_db_session):
    def _get_db():
        yield mock_db_session
    app.dependency_overrides[get_db] = _get_db
    yield
    app.dependency_overrides.clear()

def test_number_not_found(override_get_db, mock_db_session):
    # Setup: Query for PhoneNumber returns None
    mock_db_session.query.return_value.filter.return_value.first.return_value = None

    response = client.post(
        "/twilio/authorize",
        data={"To": "+391234567890", "From": "+390000000000", "CallSid": "CA123"}
    )

    assert response.status_code == 200
    assert response.json() == {"allowed": False, "reason": "Number not found"}

def test_user_not_found(override_get_db, mock_db_session):
    # Setup: PhoneNumber exists but user is None
    mock_phone = MagicMock(spec=PhoneNumber)
    mock_phone.user = None

    mock_db_session.query.return_value.filter.return_value.first.return_value = mock_phone

    response = client.post(
        "/twilio/authorize",
        data={"To": "+391234567890", "From": "+390000000000", "CallSid": "CA123"}
    )

    assert response.status_code == 200
    assert response.json() == {"allowed": False, "reason": "User not found"}

def test_user_suspended(override_get_db, mock_db_session):
    # Setup: User suspended
    mock_user = MagicMock(spec=User)
    mock_user.is_active = False

    mock_phone = MagicMock(spec=PhoneNumber)
    mock_phone.user = mock_user

    mock_db_session.query.return_value.filter.return_value.first.return_value = mock_phone

    response = client.post(
        "/twilio/authorize",
        data={"To": "+391234567890", "From": "+390000000000", "CallSid": "CA123"}
    )

    assert response.status_code == 200
    assert response.json() == {"allowed": False, "reason": "User suspended"}

def test_user_no_active_plan(override_get_db, mock_db_session):
    # Setup: User active but no plan
    mock_user = MagicMock(spec=User)
    mock_user.is_active = True
    mock_user.has_active_plan.return_value = False # Explicitly False

    mock_phone = MagicMock(spec=PhoneNumber)
    mock_phone.user = mock_user

    mock_db_session.query.return_value.filter.return_value.first.return_value = mock_phone

    response = client.post(
        "/twilio/authorize",
        data={"To": "+391234567890", "From": "+390000000000", "CallSid": "CA123"}
    )

    assert response.status_code == 200
    assert response.json() == {"allowed": False, "reason": "No active plan"}

def test_agent_disabled(override_get_db, mock_db_session):
    # Setup: User OK, Plan OK, but AgentRouting disabled
    mock_user = MagicMock(spec=User)
    mock_user.is_active = True
    mock_user.has_active_plan.return_value = True

    mock_phone = MagicMock(spec=PhoneNumber)
    mock_phone.id = 123
    mock_phone.user = mock_user

    mock_routing = MagicMock(spec=AgentRouting)
    mock_routing.is_active = False

    # Need to handle multiple queries: first for phone, second for routing
    def side_effect_query(model):
        m = MagicMock()
        if model == PhoneNumber:
            m.filter.return_value.first.return_value = mock_phone
        elif model == AgentRouting:
            m.filter.return_value.first.return_value = mock_routing
        return m

    mock_db_session.query.side_effect = side_effect_query

    response = client.post(
        "/twilio/authorize",
        data={"To": "+391234567890", "From": "+390000000000", "CallSid": "CA123"}
    )

    assert response.status_code == 200
    assert response.json() == {"allowed": False, "reason": "Agent disabled"}

def test_success(override_get_db, mock_db_session):
    # Setup: All OK
    mock_user = MagicMock(spec=User)
    mock_user.is_active = True
    mock_user.has_active_plan.return_value = True

    mock_phone = MagicMock(spec=PhoneNumber)
    mock_phone.id = 123
    mock_phone.user = mock_user

    # Case A: Routing exists and is active
    mock_routing = MagicMock(spec=AgentRouting)
    mock_routing.is_active = True

    def side_effect_query(model):
        m = MagicMock()
        if model == PhoneNumber:
            m.filter.return_value.first.return_value = mock_phone
        elif model == AgentRouting:
            m.filter.return_value.first.return_value = mock_routing
        return m

    mock_db_session.query.side_effect = side_effect_query

    response = client.post(
        "/twilio/authorize",
        data={"To": "+39 123 456 7890", "From": "+390000000000", "CallSid": "CA123"}
    )

    assert response.status_code == 200
    assert response.json() == {"allowed": True}

def test_success_no_routing(override_get_db, mock_db_session):
    # Setup: All OK, no specific agent routing record (defaults to allowed if User OK?)
    # Logic in code: "Se esiste una riga in agent_routing... se is_active == false -> blocca"
    # So if no row exists, we don't block based on agent routing.

    mock_user = MagicMock(spec=User)
    mock_user.is_active = True
    mock_user.has_active_plan.return_value = True

    mock_phone = MagicMock(spec=PhoneNumber)
    mock_phone.id = 123
    mock_phone.user = mock_user

    def side_effect_query(model):
        m = MagicMock()
        if model == PhoneNumber:
            m.filter.return_value.first.return_value = mock_phone
        elif model == AgentRouting:
            m.filter.return_value.first.return_value = None # No routing
        return m

    mock_db_session.query.side_effect = side_effect_query

    response = client.post(
        "/twilio/authorize",
        data={"To": "+391234567890", "From": "+390000000000", "CallSid": "CA123"}
    )

    assert response.status_code == 200
    assert response.json() == {"allowed": True}
