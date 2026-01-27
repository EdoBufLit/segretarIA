import pytest
from unittest.mock import MagicMock, patch
from fastapi.testclient import TestClient
from app import app
from services.call_session import CallSessionManager, CallStatus

client = TestClient(app)

@pytest.fixture
def mock_redis():
    with patch("services.call_session.get_redis_connection") as mock_get_redis:
        mock_client = MagicMock()
        mock_get_redis.return_value = mock_client
        mock_client.time.return_value = (1234567890, 0)
        yield mock_client

class TestBargeInConnect:
    def test_barge_in_connect_success(self, mock_redis):
        call_sid = "call_123"
        agent_id = "agent_007"
        office_phone = "+1234567890"

        # Redis returns bytes
        mock_redis.hgetall.return_value = {
            b"status": b"human_requested",
            b"agent_id": agent_id.encode(),
            b"office_phone_e164": office_phone.encode()
        }

        response = client.post(
            "/twilio/barge_in_connect",
            data={"CallSid": call_sid}
        )

        assert response.status_code == 200
        assert response.headers["content-type"] == "application/xml"

        xml = response.text
        assert "<Dial" in xml
        assert f"<Number>{office_phone}</Number>" in xml
        assert f'action="http://testserver/twilio/after_dial?agent_id={agent_id}"' in xml

        # Verify Status Update
        mock_redis.hset.assert_called_with(f"call_session:{call_sid}", "status", "human_connected")

    def test_barge_in_connect_invalid_status(self, mock_redis):
        call_sid = "call_123"

        mock_redis.hgetall.return_value = {
            b"status": b"ai_active", # Not human_requested
            b"agent_id": b"agent_007"
        }

        response = client.post(
            "/twilio/barge_in_connect",
            data={"CallSid": call_sid}
        )

        assert response.status_code == 200
        assert "<Hangup/>" in response.text
        # Ensure status was NOT updated
        mock_redis.hset.assert_not_called()

    def test_barge_in_connect_no_session(self, mock_redis):
        mock_redis.hgetall.return_value = {}

        response = client.post(
            "/twilio/barge_in_connect",
            data={"CallSid": "unknown"}
        )
        assert response.status_code == 200
        assert "<Hangup/>" in response.text

    def test_barge_in_connect_no_office_phone(self, mock_redis):
        call_sid = "call_123"

        mock_redis.hgetall.return_value = {
            b"status": b"human_requested",
            b"agent_id": b"agent_007"
            # Missing office_phone
        }

        response = client.post(
            "/twilio/barge_in_connect",
            data={"CallSid": call_sid}
        )

        assert response.status_code == 200
        assert "<Hangup/>" in response.text
