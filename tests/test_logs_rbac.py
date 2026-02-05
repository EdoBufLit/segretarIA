import json
import os
from unittest.mock import MagicMock, patch, ANY
from fastapi.testclient import TestClient
from app import app
from models import User, Agent
from auth import get_current_user
from db import get_db

client = TestClient(app)

def test_logs_rbac_admin_access():
    """Admin should be able to access any agent logs."""
    admin_user = User(id=1, username="admin", role="admin", email="admin@test.com")

    # Mock get_current_user
    app.dependency_overrides[get_current_user] = lambda: admin_user

    with patch("app._read_logs") as mock_read:
        mock_read.return_value = {"status": "ok", "total": 0, "items": []}

        response = client.get("/logs/any_agent_id/list")
        assert response.status_code == 200
        mock_read.assert_called_with(ANY, ['any_agent_id'], 50, 0, 'all', None, None, None)

    app.dependency_overrides = {}

def test_logs_rbac_client_access_own_agent():
    """Client should be able to access their own agent logs."""
    client_user = User(id=2, username="client", role="client", email="client@test.com")
    agent = Agent(agent_id="my_agent_id", display_name="My Agent")
    client_user.agents = [agent]

    app.dependency_overrides[get_current_user] = lambda: client_user

    # Mock DB
    mock_db = MagicMock()
    mock_db.query.return_value.filter.return_value.first.return_value = client_user
    app.dependency_overrides[get_db] = lambda: mock_db

    with patch("app._read_logs") as mock_read:
        mock_read.return_value = {"status": "ok", "total": 0, "items": []}

        response = client.get("/logs/my_agent_id/list")
        assert response.status_code == 200
        mock_read.assert_called()

    app.dependency_overrides = {}

def test_logs_rbac_client_access_other_agent():
    """Client should NOT be able to access other agent logs."""
    client_user = User(id=2, username="client", role="client", email="client@test.com")
    agent = Agent(agent_id="my_agent_id", display_name="My Agent")
    client_user.agents = [agent]

    app.dependency_overrides[get_current_user] = lambda: client_user

    # Mock DB
    mock_db = MagicMock()
    mock_db.query.return_value.filter.return_value.first.return_value = client_user
    app.dependency_overrides[get_db] = lambda: mock_db

    with patch("app._read_logs") as mock_read:
        response = client.get("/logs/other_agent_id/list")
        assert response.status_code == 403
        assert response.json()["detail"] == "Access denied to this agent"
        mock_read.assert_not_called()

    app.dependency_overrides = {}
