import os
import json
import pytest
from unittest.mock import MagicMock, patch
from fastapi.testclient import TestClient
from app import app
from models import AgentRouting, User, Subscription, Agent

client = TestClient(app)

SECRET = "test_secret_blocking"

import hmac
import hashlib
import time

def generate_signature(secret: str, body: bytes, timestamp: str = None) -> dict:
    if timestamp is None:
        timestamp = str(int(time.time()))
    payload = body + timestamp.encode("utf-8")
    signature = hmac.new(secret.encode("utf-8"), payload, hashlib.sha256).hexdigest()
    return {"elevenlabs-signature": f"t={timestamp},v1={signature}"}

@pytest.fixture
def mock_env():
    with patch.dict(os.environ, {"ELEVENLABS_WEBHOOK_SECRET": SECRET}):
        yield

@pytest.fixture
def mock_queue():
    with patch("app.get_queue") as mock_get_queue:
        mock_q = MagicMock()
        mock_get_queue.return_value = mock_q
        yield mock_q

@pytest.fixture
def mock_db_session():
    # Patch SessionLocal to return a magic mock when called as context manager
    with patch("app.SessionLocal") as mock_session_cls:
        mock_session = MagicMock()
        # Ensure __enter__ returns the mock session (standard context manager)
        mock_session_cls.return_value.__enter__.return_value = mock_session
        yield mock_session

def test_agent_disabled(mock_env, mock_queue, mock_db_session):
    # Setup mocks
    mock_routing = MagicMock(spec=AgentRouting)
    mock_routing.is_active = False

    # When query is called with AgentRouting, return the mock routing
    def query_side_effect(model):
        query_mock = MagicMock()
        if model == AgentRouting:
            query_mock.filter.return_value.first.return_value = mock_routing
        else:
            query_mock.filter.return_value.first.return_value = None
        return query_mock

    mock_db_session.query.side_effect = query_side_effect

    payload = {"type": "post_call_transcription", "data": {"agent_id": "agent_disabled"}}
    body_bytes = json.dumps(payload).encode("utf-8")
    headers = generate_signature(SECRET, body_bytes)

    response = client.post("/elevenlabs/webhook", content=body_bytes, headers=headers)

    # Expect 403 Forbidden
    assert response.status_code == 403
    assert response.json() == {"error": "Piano scaduto o agente disattivato"}
    mock_queue.enqueue.assert_not_called()

def test_user_suspended(mock_env, mock_queue, mock_db_session):
    mock_routing = MagicMock(spec=AgentRouting)
    mock_routing.is_active = True
    mock_routing.user_id = 10

    mock_user = MagicMock(spec=User)
    mock_user.is_active = False
    mock_user.username = "suspended_user"

    def query_side_effect(model):
        query_mock = MagicMock()
        if model == AgentRouting:
            query_mock.filter.return_value.first.return_value = mock_routing
        elif model == User:
            query_mock.filter.return_value.first.return_value = mock_user
        else:
            query_mock.filter.return_value.first.return_value = None
        return query_mock

    mock_db_session.query.side_effect = query_side_effect

    payload = {"type": "post_call_transcription", "data": {"agent_id": "agent_user_suspended"}}
    body_bytes = json.dumps(payload).encode("utf-8")
    headers = generate_signature(SECRET, body_bytes)

    response = client.post("/elevenlabs/webhook", content=body_bytes, headers=headers)

    assert response.status_code == 403
    assert response.json() == {"error": "Piano scaduto o agente disattivato"}
    mock_queue.enqueue.assert_not_called()

def test_user_no_active_plan(mock_env, mock_queue, mock_db_session):
    mock_routing = MagicMock(spec=AgentRouting)
    mock_routing.is_active = True
    mock_routing.user_id = 10

    mock_user = MagicMock(spec=User)
    mock_user.is_active = True
    mock_user.id = 10
    mock_user.username = "no_plan_user"
    # Essential: Mock the method to return False, otherwise MagicMock returns a truthy Mock
    mock_user.has_active_plan.return_value = False

    def query_side_effect(model):
        query_mock = MagicMock()
        if model == AgentRouting:
            query_mock.filter.return_value.first.return_value = mock_routing
        elif model == User:
            query_mock.filter.return_value.first.return_value = mock_user
        elif model == Subscription:
            # Return None to simulate no active subscription found
            query_mock.filter.return_value.first.return_value = None
        return query_mock

    mock_db_session.query.side_effect = query_side_effect

    payload = {"type": "post_call_transcription", "data": {"agent_id": "agent_no_plan"}}
    body_bytes = json.dumps(payload).encode("utf-8")
    headers = generate_signature(SECRET, body_bytes)

    response = client.post("/elevenlabs/webhook", content=body_bytes, headers=headers)

    assert response.status_code == 403
    assert response.json() == {"error": "Piano scaduto o agente disattivato"}
    mock_queue.enqueue.assert_not_called()

def test_unknown_agent_allowed(mock_env, mock_queue, mock_db_session):
    # No AgentRouting, no User -> should pass to allow unassigned event creation

    def query_side_effect(model):
        query_mock = MagicMock()
        query_mock.filter.return_value.first.return_value = None
        return query_mock

    mock_db_session.query.side_effect = query_side_effect

    payload = {"type": "post_call_transcription", "data": {"agent_id": "unknown_agent"}}
    body_bytes = json.dumps(payload).encode("utf-8")
    headers = generate_signature(SECRET, body_bytes)

    response = client.post("/elevenlabs/webhook", content=body_bytes, headers=headers)

    assert response.status_code == 200
    mock_queue.enqueue.assert_called_once()

def test_success(mock_env, mock_queue, mock_db_session):
    mock_routing = MagicMock(spec=AgentRouting)
    mock_routing.is_active = True
    mock_routing.user_id = 10

    mock_user = MagicMock(spec=User)
    mock_user.is_active = True
    mock_user.id = 10

    mock_sub = MagicMock(spec=Subscription)
    mock_sub.state = "active"

    def query_side_effect(model):
        query_mock = MagicMock()
        if model == AgentRouting:
            query_mock.filter.return_value.first.return_value = mock_routing
        elif model == User:
            query_mock.filter.return_value.first.return_value = mock_user
        elif model == Subscription:
            query_mock.filter.return_value.first.return_value = mock_sub
        return query_mock

    mock_db_session.query.side_effect = query_side_effect

    payload = {"type": "post_call_transcription", "data": {"agent_id": "good_agent"}}
    body_bytes = json.dumps(payload).encode("utf-8")
    headers = generate_signature(SECRET, body_bytes)

    response = client.post("/elevenlabs/webhook", content=body_bytes, headers=headers)

    assert response.status_code == 200
    mock_queue.enqueue.assert_called_once()
