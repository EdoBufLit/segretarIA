import pytest
from unittest.mock import MagicMock, patch
from scripts.preflight_realtime import check_env_vars, check_db_connectivity, check_routing, main
from models import AgentRouting

def test_check_env_vars_success():
    with patch.dict("os.environ", {
        "PUBLIC_BASE_URL": "https://myapp.com",
        "ELEVEN_API_KEY": "xi_test",
        "TWILIO_AUTH_TOKEN": "tw_test",
        "TWILIO_SIGNATURE_CHECK": "true"
    }):
        errors = check_env_vars()
        assert len(errors) == 0

def test_check_env_vars_missing():
    with patch.dict("os.environ", {}, clear=True):
        errors = check_env_vars()
        assert any("PUBLIC_BASE_URL" in e for e in errors)
        assert any("ELEVEN_API_KEY" in e for e in errors)
        # TWILIO_SIGNATURE_CHECK defaults to true, so missing TOKEN is error
        assert any("TWILIO_AUTH_TOKEN" in e for e in errors)

def test_check_db_connectivity_success():
    mock_db = MagicMock()
    errors = check_db_connectivity(mock_db)
    assert len(errors) == 0
    mock_db.execute.assert_called_once()

def test_check_db_connectivity_fail():
    mock_db = MagicMock()
    mock_db.execute.side_effect = Exception("DB Down")
    errors = check_db_connectivity(mock_db)
    assert len(errors) == 1
    assert "DB Down" in errors[0]

def test_check_routing_success():
    mock_db = MagicMock()
    mock_routing = MagicMock(spec=AgentRouting)
    mock_routing.agent_id = "agent_123"

    mock_db.query.return_value.filter.return_value.all.return_value = [mock_routing]

    errors = check_routing(mock_db)
    assert len(errors) == 0

def test_check_routing_no_active():
    mock_db = MagicMock()
    mock_db.query.return_value.filter.return_value.all.return_value = []

    errors = check_routing(mock_db)
    assert len(errors) == 1
    assert "No active AgentRouting" in errors[0]

def test_check_routing_invalid_id():
    mock_db = MagicMock()
    mock_routing = MagicMock(spec=AgentRouting)
    mock_routing.agent_id = "" # Invalid

    mock_db.query.return_value.filter.return_value.all.return_value = [mock_routing]

    errors = check_routing(mock_db)
    assert len(errors) == 1
    assert "invalid agent_id" in errors[0]

@patch("scripts.preflight_realtime.SessionLocal")
def test_main_success(mock_session_cls):
    mock_db = MagicMock()
    mock_session_cls.return_value = mock_db

    # Mock routing success
    mock_routing = MagicMock(spec=AgentRouting)
    mock_routing.agent_id = "agent_ok"
    mock_db.query.return_value.filter.return_value.all.return_value = [mock_routing]

    with patch.dict("os.environ", {
        "PUBLIC_BASE_URL": "https://ok.com",
        "ELEVEN_API_KEY": "ok",
        "TWILIO_SIGNATURE_CHECK": "false"
    }):
        with pytest.raises(SystemExit) as exc:
            main()
        assert exc.value.code == 0

@patch("scripts.preflight_realtime.SessionLocal")
def test_main_fail(mock_session_cls):
    mock_db = MagicMock()
    mock_session_cls.return_value = mock_db

    # Mock routing failure
    mock_db.query.return_value.filter.return_value.all.return_value = []

    with patch.dict("os.environ", {
        "PUBLIC_BASE_URL": "https://ok.com",
        "ELEVEN_API_KEY": "ok",
    }):
        with pytest.raises(SystemExit) as exc:
            main()
        assert exc.value.code == 1
