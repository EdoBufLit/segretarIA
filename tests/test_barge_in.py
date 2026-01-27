import pytest
from unittest.mock import MagicMock, patch, AsyncMock
from fastapi.testclient import TestClient
from app import app
from services.call_session import CallSessionManager, CallStatus
from services.realtime_bridge import active_sessions
from models import User, Agent
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
    user.agents = []

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

@pytest.fixture
def mock_twilio_client():
    with patch("app.twilio_client") as mock_client:
        if mock_client is None:
            mock_client = MagicMock()
        yield mock_client

class TestBargeIn:
    def test_barge_in_success(self, mock_db, mock_current_user, mock_redis, mock_twilio_client):
        # Setup Redis Session
        call_sid = "call_123"
        agent_id = "agent_007"

        mock_redis.hgetall.return_value = {
            b"status": b"ai_active",
            b"agent_id": agent_id.encode(),
            b"office_phone_e164": b"+1234567890"
        }

        # Setup User Auth (owns agent)
        agent = MagicMock(spec=Agent)
        agent.agent_id = agent_id
        mock_current_user.agents = [agent]

        # Setup Active Session (for terminate check)
        mock_ws_session = AsyncMock()
        active_sessions[call_sid] = mock_ws_session

        try:
            response = client.post(f"/calls/{call_sid}/barge-in")
        finally:
            # Clean up active_sessions
            if call_sid in active_sessions:
                del active_sessions[call_sid]

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "ok"
        assert data["call_status"] == "human_requested"

        # Verify Redis Update
        mock_redis.hset.assert_called_with(f"call_session:{call_sid}", "status", "human_requested")

        # Verify WebSocket Termination
        mock_ws_session.close.assert_called()

        # Verify Twilio Redirect
        mock_twilio_client.calls.return_value.update.assert_called_once()
        args, kwargs = mock_twilio_client.calls.return_value.update.call_args
        assert '<Dial timeout="15"' in kwargs['twiml']

    def test_barge_in_not_found(self, mock_redis, mock_current_user):
        mock_redis.hgetall.return_value = {}
        response = client.post("/calls/unknown_sid/barge-in")
        assert response.status_code == 404

    def test_barge_in_wrong_status(self, mock_redis, mock_current_user):
        mock_redis.hgetall.return_value = {
            b"status": b"ended",
            b"agent_id": b"agent_007"
        }
        response = client.post("/calls/call_123/barge-in")
        assert response.status_code == 400

    def test_barge_in_access_denied(self, mock_db, mock_current_user, mock_redis):
        # Redis Session
        agent_id = "agent_007"
        mock_redis.hgetall.return_value = {
            b"status": b"ai_active",
            b"agent_id": agent_id.encode()
        }

        # User has NO agents
        mock_current_user.agents = []

        # Fallback check also fails
        mock_db.query.return_value.filter.return_value.first.return_value = None

        response = client.post("/calls/call_123/barge-in")
        assert response.status_code == 403

    def test_barge_in_admin_access(self, mock_db, mock_current_user, mock_redis):
        mock_current_user.role = "admin"
        agent_id = "agent_007"
        mock_redis.hgetall.return_value = {
            b"status": b"ai_active",
            b"agent_id": agent_id.encode(),
            b"office_phone_e164": b"+1234567890"
        }

        response = client.post("/calls/call_123/barge-in")
        assert response.status_code == 200
