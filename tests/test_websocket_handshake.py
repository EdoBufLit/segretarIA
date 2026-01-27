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
mock_query = mock_db.query.return_value
mock_filter = mock_query.filter.return_value
mock_filter.first.return_value = mock_agent_routing

def override_get_db():
    try:
        yield mock_db
    finally:
        pass

app.dependency_overrides[get_db] = override_get_db

def test_websocket_late_binding_ignores_connected_event():
    """
    Test that the WebSocket ignores the 'connected' event and waits for 'start'.
    """
    with patch("services.realtime_bridge.RealtimeSession.start", new_callable=AsyncMock) as mock_start:
        with patch("services.realtime_bridge.RealtimeSession.__init__", return_value=None) as mock_init:
            with patch("app.CallSessionManager") as MockCSM:
                mock_mgr = MockCSM.return_value
                mock_mgr.get_session.return_value = {"agent_id": "test-agent-redis"}

                client = TestClient(app)

                with client.websocket_connect("/ws/twilio") as websocket:
                    # 1. Send 'connected' event (should be ignored)
                    connected_payload = {
                        "event": "connected",
                        "protocol": "Call",
                        "version": "1.0.0"
                    }
                    websocket.send_json(connected_payload)

                    # 2. Send 'start' event
                    start_payload = {
                        "event": "start",
                        "start": {
                            "streamSid": "MZ123",
                            "callSid": "CA_CONNECTED_TEST",
                            "customParameters": {}
                        }
                    }
                    websocket.send_json(start_payload)

                # Verify session was initialized with the agent from Redis
                mock_mgr.get_session.assert_called_with("CA_CONNECTED_TEST")
                mock_init.assert_called_once()
                args, _ = mock_init.call_args
                assert args[1] == "test-agent-redis"

def test_websocket_late_binding_success_redis():
    """
    Test that the WebSocket resolves agent_id from Redis using callSid.
    """
    with patch("services.realtime_bridge.RealtimeSession.start", new_callable=AsyncMock) as mock_start:
        with patch("services.realtime_bridge.RealtimeSession.__init__", return_value=None) as mock_init:
            with patch("app.CallSessionManager") as MockCSM:
                mock_mgr = MockCSM.return_value
                mock_mgr.get_session.return_value = {"agent_id": "test-agent-redis"}

                client = TestClient(app)

                with client.websocket_connect("/ws/twilio") as websocket:
                    start_payload = {
                        "event": "start",
                        "start": {
                            "streamSid": "MZ123",
                            "callSid": "CA_REDIS_TEST",
                            "customParameters": {}
                        }
                    }
                    websocket.send_json(start_payload)

                mock_mgr.get_session.assert_called_with("CA_REDIS_TEST")
                mock_init.assert_called_once()
                args, _ = mock_init.call_args
                assert args[1] == "test-agent-redis"

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
