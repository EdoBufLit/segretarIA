import pytest
import json
from fastapi.testclient import TestClient
from unittest.mock import MagicMock, patch, AsyncMock
from app import app, get_db
from services.realtime_bridge import RealtimeSession

# Mock DB
mock_db = MagicMock()
mock_agent_routing = MagicMock()
mock_agent_routing.agent_id = "test-agent-123"
mock_agent_routing.is_active = True

# Setup query chain
# db.query(AgentRouting).filter(...).first()
mock_query = mock_db.query.return_value
mock_filter = mock_query.filter.return_value
mock_filter.first.return_value = mock_agent_routing

def override_get_db():
    try:
        yield mock_db
    finally:
        pass

@pytest.fixture(autouse=True)
def _db_override():
    app.dependency_overrides[get_db] = override_get_db
    yield
    app.dependency_overrides.pop(get_db, None)

def test_websocket_late_binding_success_redis():
    """
    Test that the WebSocket resolves agent_id from Redis using callSid.
    """
    with patch("services.realtime_bridge.RealtimeSession.start", new_callable=AsyncMock) as mock_start:
        with patch("services.realtime_bridge.RealtimeSession.__init__", return_value=None) as mock_init:
            # Mock CallSessionManager
            with patch("app.CallSessionManager") as MockCSM:
                mock_mgr = MockCSM.return_value
                mock_mgr.get_session.return_value = {"agent_id": "test-agent-redis"}

                client = TestClient(app)

                # 1. Connect
                with client.websocket_connect("/ws/twilio") as websocket:
                    # 2. Send 'start' event with callSid
                    start_payload = {
                        "event": "start",
                        "start": {
                            "streamSid": "MZ123",
                            "callSid": "CA_REDIS_TEST",
                            "customParameters": {} # Empty params
                        }
                    }
                    websocket.send_json(start_payload)

                # Verify Redis was checked
                mock_mgr.get_session.assert_called_with("CA_REDIS_TEST")

                # Verify Session Init used Redis agent_id
                mock_init.assert_called_once()
                args, _ = mock_init.call_args
                assert args[1] == "test-agent-redis"

def test_websocket_late_binding_fallback_params():
    """
    Test fallback to customParameters if Redis fails or returns empty.
    """
    with patch("services.realtime_bridge.RealtimeSession.start", new_callable=AsyncMock) as mock_start:
        with patch("services.realtime_bridge.RealtimeSession.__init__", return_value=None) as mock_init:
            with patch("app.CallSessionManager") as MockCSM:
                mock_mgr = MockCSM.return_value
                mock_mgr.get_session.return_value = None # No session found

                client = TestClient(app)

                with client.websocket_connect("/ws/twilio") as websocket:
                    start_payload = {
                        "event": "start",
                        "start": {
                            "streamSid": "MZ123",
                            "callSid": "CA_FALLBACK_TEST",
                            "customParameters": {
                                "agent_id": "test-agent-fallback"
                            }
                        }
                    }
                    websocket.send_json(start_payload)

                mock_init.assert_called_once()
                args, _ = mock_init.call_args
                assert args[1] == "test-agent-fallback"

def test_websocket_late_binding_failure_no_agent():
    """
    Test failure when neither Redis nor params provide agent_id.
    """
    with patch("services.realtime_bridge.RealtimeSession.start", new_callable=AsyncMock):
        with patch("app.CallSessionManager") as MockCSM:
            mock_mgr = MockCSM.return_value
            mock_mgr.get_session.return_value = None

            client = TestClient(app)

            with pytest.raises(Exception):
                with client.websocket_connect("/ws/twilio") as websocket:
                    start_payload = {
                        "event": "start",
                        "start": {
                            "streamSid": "MZ123",
                            "callSid": "CA_FAIL",
                            "customParameters": {}
                        }
                    }
                    websocket.send_json(start_payload)
                    websocket.receive_text() # Should receive close
