import pytest
from fastapi.testclient import TestClient
from unittest.mock import MagicMock, patch, AsyncMock
import os
from app import app
from db import get_db
from services.realtime_bridge import RealtimeSession
from models import PhoneNumber, AgentRouting, User

client = TestClient(app)

@pytest.fixture
def allow_twilio_signature():
    with patch("app.validate_twilio_signature", new=AsyncMock(return_value=True)):
        yield

def test_realtime_session_structure():
    """
    Verifies that RealtimeSession has the expected methods.
    """
    mock_ws = MagicMock()
    session = RealtimeSession(mock_ws, "test_agent")
    assert hasattr(session, "start")
    assert hasattr(session, "handle_twilio_messages")
    assert hasattr(session, "handle_eleven_messages")

def test_twilio_voice_endpoint(allow_twilio_signature):
    """
    Verifies that POST /twilio/voice returns correct TwiML when agent is found and user is active/paying.
    """
    # Mock DB Session
    mock_db = MagicMock()

    # Mock User
    mock_user = MagicMock(spec=User)
    mock_user.is_active = True
    mock_user.has_active_plan.return_value = True

    # Mock Phone
    mock_phone = MagicMock(spec=PhoneNumber)
    mock_phone.id = 1
    mock_phone.e164 = "+1234567890"
    mock_phone.user = mock_user

    # Mock Routing
    mock_routing = MagicMock(spec=AgentRouting)
    mock_routing.agent_id = "agent_abc123"
    mock_routing.is_active = True

    # Setup Query Chain
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

def test_twilio_voice_user_suspended(allow_twilio_signature):
    """
    Verifies that POST /twilio/voice rejects call if user is suspended.
    """
    mock_db = MagicMock()

    mock_user = MagicMock(spec=User)
    mock_user.is_active = False # Suspended
    mock_user.has_active_plan.return_value = True

    mock_phone = MagicMock(spec=PhoneNumber)
    mock_phone.id = 1
    mock_phone.e164 = "+1234567890"
    mock_phone.user = mock_user

    def query_side_effect(model):
        query_mock = MagicMock()
        if model == PhoneNumber:
            query_mock.filter.return_value.first.return_value = mock_phone
        return query_mock

    mock_db.query.side_effect = query_side_effect
    app.dependency_overrides[get_db] = lambda: mock_db

    try:
        response = client.post(
            "/twilio/voice",
            data={"To": "+1234567890", "From": "+0987654321", "CallSid": "CA12345"}
        )
        assert response.status_code == 200
        content = response.text
        assert "<Hangup/>" in content
        assert "non è configurato correttamente" in content # Generic message
    finally:
        app.dependency_overrides = {}

def test_twilio_voice_no_plan(allow_twilio_signature):
    """
    Verifies that POST /twilio/voice rejects call if user has no active plan.
    """
    mock_db = MagicMock()

    mock_user = MagicMock(spec=User)
    mock_user.is_active = True
    mock_user.has_active_plan.return_value = False # No Plan

    mock_phone = MagicMock(spec=PhoneNumber)
    mock_phone.id = 1
    mock_phone.e164 = "+1234567890"
    mock_phone.user = mock_user

    def query_side_effect(model):
        query_mock = MagicMock()
        if model == PhoneNumber:
            query_mock.filter.return_value.first.return_value = mock_phone
        return query_mock

    mock_db.query.side_effect = query_side_effect
    app.dependency_overrides[get_db] = lambda: mock_db

    try:
        response = client.post(
            "/twilio/voice",
            data={"To": "+1234567890", "From": "+0987654321", "CallSid": "CA12345"}
        )
        assert response.status_code == 200
        content = response.text
        assert "<Hangup/>" in content
    finally:
        app.dependency_overrides = {}

def test_twilio_voice_no_agent(allow_twilio_signature):
    """
    Verifies fallback when no agent is found (Number not found).
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

def test_twilio_voice_signature_validation():
    """
    Verifies that POST /twilio/voice rejects requests with invalid signatures.
    """
    with patch("app.validate_twilio_signature", new=AsyncMock(return_value=False)):
        response = client.post(
            "/twilio/voice",
            data={"To": "+1234567890", "From": "+0987654321", "CallSid": "CA12345"},
            headers={"X-Twilio-Signature": "invalid_sig"}
        )

    assert response.status_code == 403
    assert "Invalid Signature" in response.text
