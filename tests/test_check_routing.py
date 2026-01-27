import pytest
from unittest.mock import MagicMock
from scripts.check_routing import resolve_routing
from models import PhoneNumber, AgentRouting, User

def test_resolve_routing_success():
    mock_db = MagicMock()

    mock_user = MagicMock(spec=User)
    mock_user.id = 10
    mock_user.is_active = True
    mock_user.has_active_plan.return_value = True

    mock_phone = MagicMock(spec=PhoneNumber)
    mock_phone.id = 1
    mock_phone.e164 = "+1234567890"
    mock_phone.user = mock_user

    mock_routing = MagicMock(spec=AgentRouting)
    mock_routing.agent_id = "agent_abc"
    mock_routing.is_active = True

    # Mock chain
    # 1. Phone lookup
    mock_db.query.return_value.filter.return_value.first.side_effect = [
        mock_phone,   # Phone
        mock_routing  # Routing
    ]

    result = resolve_routing(mock_db, "+1234567890")

    assert result["routing_found"] is True
    assert result["agent_id"] == "agent_abc"
    assert result["user_id"] == 10
    assert result["reason"] is None

def test_resolve_routing_number_not_found():
    mock_db = MagicMock()
    mock_db.query.return_value.filter.return_value.first.return_value = None

    result = resolve_routing(mock_db, "+1234567890")

    assert result["routing_found"] is False
    assert result["reason"] == "Number not found"

def test_resolve_routing_user_suspended():
    mock_db = MagicMock()

    mock_user = MagicMock(spec=User)
    mock_user.is_active = False
    mock_user.has_active_plan.return_value = True

    mock_phone = MagicMock(spec=PhoneNumber)
    mock_phone.user = mock_user

    mock_db.query.return_value.filter.return_value.first.return_value = mock_phone

    result = resolve_routing(mock_db, "+1234567890")

    assert result["routing_found"] is False
    assert result["reason"] == "User suspended"

def test_resolve_routing_no_plan():
    mock_db = MagicMock()

    mock_user = MagicMock(spec=User)
    mock_user.is_active = True
    mock_user.has_active_plan.return_value = False

    mock_phone = MagicMock(spec=PhoneNumber)
    mock_phone.user = mock_user

    mock_db.query.return_value.filter.return_value.first.return_value = mock_phone

    result = resolve_routing(mock_db, "+1234567890")

    assert result["routing_found"] is False
    assert result["reason"] == "No active plan"

def test_resolve_routing_agent_not_found():
    mock_db = MagicMock()

    mock_user = MagicMock(spec=User)
    mock_user.is_active = True
    mock_user.has_active_plan.return_value = True

    mock_phone = MagicMock(spec=PhoneNumber)
    mock_phone.user = mock_user

    # Phone found, but Routing not found
    mock_db.query.return_value.filter.return_value.first.side_effect = [
        mock_phone,
        None
    ]

    result = resolve_routing(mock_db, "+1234567890")

    assert result["routing_found"] is False
    assert result["reason"] == "Agent disabled or not configured"
