import pytest
from unittest.mock import MagicMock, patch
from fastapi.testclient import TestClient
from app import app
from services.call_session import CallSessionManager, CallStatus
from models import User
from auth import get_current_user, get_db

client = TestClient(app)

@pytest.fixture
def mock_db():
    mock_session = MagicMock()
    app.dependency_overrides[get_db] = lambda: mock_session
    yield mock_session
    app.dependency_overrides.pop(get_db, None)

@pytest.fixture
def mock_current_user():
    user = MagicMock(spec=User)
    user.id = 1
    user.role = "client"

    app.dependency_overrides[get_current_user] = lambda: user
    yield user
    app.dependency_overrides.pop(get_current_user, None)

@pytest.fixture
def mock_redis():
    with patch("services.call_session.get_redis_connection") as mock_get_redis:
        mock_client = MagicMock()
        mock_get_redis.return_value = mock_client
        mock_client.time.return_value = (1234567890, 0)
        yield mock_client

class TestActiveCallApi:
    def test_get_active_call_found(self, mock_redis, mock_current_user):
        user_id = 1
        call_sid = "call_123"

        # Mock user mapping lookup
        mock_redis.get.return_value = call_sid.encode()

        # Mock session lookup (bytes)
        mock_redis.hgetall.return_value = {
            b"status": b"ai_active",
            b"call_sid": b"call_123",
            b"office_phone_e164": b"+39021234567",
            b"caller_number": b"+393331234567",
            b"agent_id": b"agent_007"
        }

        response = client.get("/api/client/active-call")

        # Verify redis calls
        mock_redis.get.assert_called_with(f"active_call_user:{user_id}")
        mock_redis.hgetall.assert_called_with(f"call_session:{call_sid}")

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "ok"
        assert data["active_call"]["call_sid"] == call_sid
        assert data["active_call"]["status"] == "ai_active"
        assert data["active_call"]["caller_number"] == "+393331234567"

    def test_get_active_call_none(self, mock_redis, mock_current_user):
        mock_redis.get.return_value = None

        response = client.get("/api/client/active-call")

        assert response.status_code == 200
        data = response.json()
        assert data["active_call"] is None

    def test_get_active_call_ended_status(self, mock_redis, mock_current_user):
        # Even if user mapping exists, if session is ended, return None
        mock_redis.get.return_value = b"call_ended_123"
        mock_redis.hgetall.return_value = {
            b"status": b"ended"
        }

        response = client.get("/api/client/active-call")
        data = response.json()
        assert data["active_call"] is None

class TestCallSessionManagerUserMapping:
    def test_start_session_sets_mapping(self, mock_redis):
        mgr = CallSessionManager()
        mgr.start_session(
            call_sid="call_999",
            agent_id="agent_x",
            phone_number_id=10,
            status=CallStatus.AI_ACTIVE,
            user_id=55,
            caller_number="+39333"
        )

        # Verify mapping set
        mock_redis.setex.assert_called_with("active_call_user:55", 3600, "call_999")

        # Verify hash fields
        args, kwargs = mock_redis.hset.call_args
        mapping = kwargs['mapping']
        assert mapping["user_id"] == "55"
        assert mapping["caller_number"] == "+39333"

    def test_end_session_clears_mapping(self, mock_redis):
        # Mock get_session to return user_id
        mock_redis.hgetall.return_value = {
            b"user_id": b"55",
            b"status": b"ai_active"
        }

        mgr = CallSessionManager()
        mgr.end_session("call_999")

        mock_redis.delete.assert_called_with("active_call_user:55")
