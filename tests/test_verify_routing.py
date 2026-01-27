import pytest
from unittest.mock import MagicMock
from scripts.verify_routing import verify_routing
from models import PhoneNumber, AgentRouting, User

def test_verify_routing_success():
    mock_db = MagicMock()

    mock_user = MagicMock(spec=User)
    mock_user.id = 2
    mock_user.is_active = True
    mock_user.has_active_plan.return_value = True

    mock_phone = MagicMock(spec=PhoneNumber)
    mock_phone.id = 5
    mock_phone.e164 = "+390299914306"
    mock_phone.user_id = 2
    mock_phone.user = mock_user

    mock_routing = MagicMock(spec=AgentRouting)
    mock_routing.id = 10
    mock_routing.phone_number_id = 5
    mock_routing.user_id = 2
    mock_routing.agent_id = "agent_xyz"
    mock_routing.is_active = True

    mock_db.query.return_value.filter.return_value.first.side_effect = [
        mock_phone,   # 1. Lookup PhoneNumber
        mock_routing, # 3. Lookup AgentRouting
    ]

    report = verify_routing(mock_db, "+39 02 9991 4306", 2, "agent_xyz")

    assert report["status"] == "PASS"
    assert report["runtime_resolution"]["resolved"] is True
    assert "Found PhoneNumber ID 5" in report["findings"][0]

def test_verify_routing_phone_not_found():
    mock_db = MagicMock()
    mock_db.query.return_value.filter.return_value.first.return_value = None # Phone not found
    mock_db.query.return_value.filter.return_value.all.return_value = [] # Fuzzy not found

    report = verify_routing(mock_db, "+39000", 2, "agent_x")
    assert report["status"] == "FAIL"
    assert "PhoneNumber not found" in report["findings"][0]

def test_verify_routing_user_mismatch():
    mock_db = MagicMock()

    mock_phone = MagicMock(spec=PhoneNumber)
    mock_phone.id = 5
    mock_phone.user_id = 99 # Mismatch

    # We also need a mock routing to be returned for the next query in verify_routing,
    # because even if phone matches (or not), the code queries routing by phone_id.
    # Logic in verify_routing:
    # 1. phone = db...first()
    # 2. if not phone -> return
    # 3. check phone.user_id != expected -> set FAIL but CONTINUE
    # 4. routing = db...first()
    # 5. if not routing -> FAIL return

    # So we need mock_routing.
    mock_routing = MagicMock(spec=AgentRouting)
    mock_routing.user_id = 99
    mock_routing.agent_id = "agent_x"

    mock_db.query.return_value.filter.return_value.first.side_effect = [
        mock_phone,
        mock_routing
    ]

    # Also we need mock_phone.user for runtime check at end
    mock_user = MagicMock(spec=User)
    mock_user.id = 99
    mock_user.is_active = True
    mock_user.has_active_plan.return_value = True
    mock_phone.user = mock_user

    report = verify_routing(mock_db, "+39...", 2, "agent_x")
    assert report["status"] == "FAIL"
    assert any("PhoneNumber.user_id mismatch" in f for f in report["findings"])

def test_verify_routing_agent_mismatch():
    mock_db = MagicMock()

    mock_phone = MagicMock(spec=PhoneNumber)
    mock_phone.id = 5
    mock_phone.user_id = 2

    mock_routing = MagicMock(spec=AgentRouting)
    mock_routing.user_id = 2
    mock_routing.agent_id = "agent_WRONG"
    mock_routing.is_active = True

    mock_db.query.return_value.filter.return_value.first.side_effect = [
        mock_phone,
        mock_routing
    ]

    # We also need mock_phone.user for runtime resolution check logic
    # if the code reached there. But agent mismatch fails before runtime check usually?
    # Let's check logic: logic proceeds to check details, sets FAIL, then tries runtime.
    # So we need user setup.
    mock_user = MagicMock(spec=User)
    mock_user.is_active = True
    mock_user.has_active_plan.return_value = True
    mock_phone.user = mock_user

    report = verify_routing(mock_db, "+39...", 2, "agent_correct")
    assert report["status"] == "FAIL"
    assert any("AgentRouting.agent_id mismatch" in f for f in report["findings"])
