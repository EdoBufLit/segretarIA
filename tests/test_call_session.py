import pytest
from unittest.mock import MagicMock, patch
from services.call_session import CallSessionManager, CallStatus

class TestCallSessionManager:
    @pytest.fixture
    def mock_redis(self):
        with patch("services.call_session.get_redis_connection") as mock_get_redis:
            mock_client = MagicMock()
            mock_get_redis.return_value = mock_client
            # Mock time for started_at
            mock_client.time.return_value = (1234567890, 0)
            yield mock_client

    def test_start_session(self, mock_redis):
        mgr = CallSessionManager()
        mgr.start_session("call_123", "agent_007", 1, CallStatus.AI_ACTIVE, "+123456789")

        mock_redis.hset.assert_called_with(
            "call_session:call_123",
            mapping={
                "status": "ai_active",
                "agent_id": "agent_007",
                "phone_number_id": "1",
                "started_at": "1234567890",
                "office_phone_e164": "+123456789"
            }
        )
        mock_redis.expire.assert_called_with("call_session:call_123", 86400)

    def test_update_status_exists(self, mock_redis):
        mock_redis.exists.return_value = True
        mgr = CallSessionManager()
        mgr.update_status("call_123", CallStatus.HUMAN_CONNECTED)

        mock_redis.hset.assert_called_with("call_session:call_123", "status", "human_connected")

    def test_update_status_not_exists(self, mock_redis):
        mock_redis.exists.return_value = False
        mgr = CallSessionManager()
        mgr.update_status("call_123", CallStatus.HUMAN_CONNECTED)

        mock_redis.hset.assert_not_called()

    def test_update_stream_sid(self, mock_redis):
        mock_redis.exists.return_value = True
        mgr = CallSessionManager()
        mgr.update_stream_sid("call_123", "stream_456")

        mock_redis.hset.assert_called_with("call_session:call_123", "stream_sid", "stream_456")

    def test_end_session(self, mock_redis):
        mock_redis.exists.return_value = True
        mgr = CallSessionManager()
        mgr.end_session("call_123")

        mock_redis.hset.assert_called_with("call_session:call_123", "status", "ended")
        mock_redis.expire.assert_called_with("call_session:call_123", 3600)

    def test_get_session(self, mock_redis):
        # Redis returns bytes
        mock_redis.hgetall.return_value = {
            b"status": b"ai_active",
            b"agent_id": b"agent_007"
        }
        mgr = CallSessionManager()
        session = mgr.get_session("call_123")

        assert session == {
            "status": "ai_active",
            "agent_id": "agent_007"
        }
