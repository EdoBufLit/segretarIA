from unittest.mock import MagicMock, patch

import httpx
from fastapi.testclient import TestClient

import app as app_module
from app import app, get_db, get_current_admin_user
from models import Agent, AgentSettings, Subscription, User

client = TestClient(app)


def test_test_call_returns_502_on_httpx_error(monkeypatch):
    settings = AgentSettings(
        agent_id="agent-1",
        agent_phone_number_id="phone-id",
        test_phone_number="+390000000000",
    )

    mock_user = MagicMock(spec=User)
    mock_user.is_active = True

    mock_db = MagicMock()

    def query_side_effect(model):
        query = MagicMock()
        if model == Agent:
            query.filter_by.return_value.first.return_value = None
        elif model == AgentSettings:
            query.filter.return_value.first.return_value = settings
        return query

    mock_db.query.side_effect = query_side_effect

    app.dependency_overrides[get_db] = lambda: mock_db
    app.dependency_overrides[get_current_admin_user] = lambda: MagicMock()

    class DummyClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        async def post(self, *args, **kwargs):
            raise httpx.HTTPError("boom")

    monkeypatch.setattr(app_module, "ELEVEN_API_KEY", "test-key")

    try:
        with patch("app.httpx.AsyncClient", return_value=DummyClient()):
            response = client.post("/api/admin/agents/agent-1/test-call")
    finally:
        app.dependency_overrides.pop(get_db, None)
        app.dependency_overrides.pop(get_current_admin_user, None)

    assert response.status_code == 502
