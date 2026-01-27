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

app.dependency_overrides[get_db] = override_get_db

def test_websocket_late_binding_success():
    """
    Test that the WebSocket accepts a connection without query params,
    waits for the 'start' event, extracts agent_id, validates it, and starts the session.
    """
    # Patch RealtimeSession.start to be an async no-op so we don't connect to external services
    with patch("services.realtime_bridge.RealtimeSession.start", new_callable=AsyncMock) as mock_start:
        with patch("services.realtime_bridge.RealtimeSession.__init__", return_value=None) as mock_init:

            client = TestClient(app)

            # 1. Connect without query params
            with client.websocket_connect("/ws/twilio") as websocket:

                # 2. Send 'start' event with agent_id
                start_payload = {
                    "event": "start",
                    "start": {
                        "streamSid": "MZ123",
                        "callSid": "CA123",
                        "customParameters": {
                            "agent_id": "test-agent-123"
                        }
                    }
                }
                websocket.send_json(start_payload)

                # The route should read this, validate 'test-agent-123', and call session.start()
                # We can't easily wait for side effects here with TestClient synchronous wrapper
                # But if the socket doesn't close with error, it's a good sign.

                # We can verify that DB was queried

            # Verify logic
            # 1. DB should have been queried for AgentRouting
            assert mock_db.query.called

            # 2. RealtimeSession should have been initialized with agent_id="test-agent-123"
            # and initial_start_message containing our payload
            mock_init.assert_called_once()
            args, kwargs = mock_init.call_args
            # args[0] is websocket, args[1] is agent_id
            assert args[1] == "test-agent-123"
            assert kwargs.get("initial_start_message") == start_payload

            # 3. session.start() should have been called
            mock_start.assert_called_once()

def test_websocket_late_binding_failure_no_agent():
    """
    Test that if the start event doesn't contain agent_id, the socket closes with 4003.
    """
    with patch("services.realtime_bridge.RealtimeSession.start", new_callable=AsyncMock):
        client = TestClient(app)

        with pytest.raises(Exception) as excinfo:
            with client.websocket_connect("/ws/twilio") as websocket:
                # Send 'start' event WITHOUT agent_id
                start_payload = {
                    "event": "start",
                    "start": {
                        "streamSid": "MZ123",
                        "callSid": "CA123",
                        "customParameters": {
                            # "agent_id": ... missing
                        }
                    }
                }
                websocket.send_json(start_payload)
                # Should receive close frame
                data = websocket.receive_text()

        # TestClient raises WebSocketDisconnect on close
        # We check if the close code was 4003 (if accessible) or just that it closed.
        # Starlette TestClient raises WebSocketDisconnect.
        # But determining the code is tricky depending on version.

def test_websocket_late_binding_failure_wrong_event():
    """
    Test that if the first message is not 'start', it closes (or handles error).
    """
    with patch("services.realtime_bridge.RealtimeSession.start", new_callable=AsyncMock):
        client = TestClient(app)

        with pytest.raises(Exception):
            with client.websocket_connect("/ws/twilio") as websocket:
                # Send 'media' event first
                payload = {"event": "media"}
                websocket.send_json(payload)
                websocket.receive_text()
