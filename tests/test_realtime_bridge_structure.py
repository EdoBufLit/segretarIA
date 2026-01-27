import pytest
from fastapi.testclient import TestClient
from unittest.mock import MagicMock, patch
from app import app
from db import get_db
from services.realtime_bridge import RealtimeSession
from models import PhoneNumber, AgentRouting, User

client = TestClient(app)

def test_realtime_session_structure():
    """
    Verifies that RealtimeSession has the expected methods.
    """
    mock_ws = MagicMock()
    session = RealtimeSession(mock_ws, "test_agent")
    assert hasattr(session, "start")
    assert hasattr(session, "handle_twilio_messages")
    assert hasattr(session, "handle_eleven_messages")

def test_twilio_voice_endpoint():
    """
    Verifies that POST /twilio/voice returns correct TwiML when agent is found.
    """
    # Mock DB Session
    mock_db = MagicMock()

    # Mock Data
    mock_phone = MagicMock(spec=PhoneNumber)
    mock_phone.id = 1
    mock_phone.e164 = "+1234567890"

    mock_routing = MagicMock(spec=AgentRouting)
    mock_routing.agent_id = "agent_abc123"
    mock_routing.is_active = True

    # Setup Query Chain
    # We need to handle chained calls: db.query().filter().first()
    # 1. db.query(PhoneNumber) -> returns query_obj_1
    # 2. query_obj_1.filter(...) -> returns query_obj_2
    # 3. query_obj_2.first() -> returns mock_phone

    # Since side_effect is tricky with different args to query(), we can use a side_effect function
    def query_side_effect(model):
        query_mock = MagicMock()
        if model == PhoneNumber:
            query_mock.filter.return_value.first.return_value = mock_phone
        elif model == AgentRouting:
            query_mock.filter.return_value.first.return_value = mock_routing
        return query_mock

    mock_db.query.side_effect = query_side_effect

    # Override Dependency
    app.dependency_overrides[get_db] = lambda: mock_db

    try:
        response = client.post(
            "/twilio/voice",
            data={
                "To": "+1234567890",
                "From": "+0987654321",
                "CallSid": "CA12345"
            }
        )

        assert response.status_code == 200
        assert response.headers["content-type"] == "application/xml"
        content = response.text
        assert "<Connect>" in content
        assert "<Stream" in content
        # Check that the agent_id is correctly injected
        assert "agent_id=agent_abc123" in content

    finally:
        app.dependency_overrides = {}

def test_twilio_voice_no_agent():
    """
    Verifies fallback when no agent is found.
    """
    mock_db = MagicMock()

    # Return None for PhoneNumber
    def query_side_effect(model):
        query_mock = MagicMock()
        query_mock.filter.return_value.first.return_value = None
        return query_mock

    mock_db.query.side_effect = query_side_effect

    app.dependency_overrides[get_db] = lambda: mock_db

    try:
        response = client.post(
            "/twilio/voice",
            data={
                "To": "+1234567890",
                "From": "+0987654321",
                "CallSid": "CA12345"
            }
        )

        assert response.status_code == 200
        content = response.text
        assert "<Hangup/>" in content
    finally:
        app.dependency_overrides = {}
