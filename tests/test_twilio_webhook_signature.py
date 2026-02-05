from unittest.mock import AsyncMock, MagicMock, patch

from fastapi.testclient import TestClient

from app import app
from db import get_db
from models import AgentRouting, PhoneNumber, User

client = TestClient(app)


def test_twilio_authorize_rejects_invalid_signature():
    with patch("app.validate_twilio_signature", new=AsyncMock(return_value=False)):
        response = client.post(
            "/twilio/authorize",
            data={"To": "+391234567890", "From": "+390000000000", "CallSid": "CA123"},
        )

    assert response.status_code == 403


def test_twilio_voice_returns_twiml_xml():
    mock_db = MagicMock()

    mock_user = MagicMock(spec=User)
    mock_user.is_active = True
    mock_user.has_active_plan.return_value = True

    mock_phone = MagicMock(spec=PhoneNumber)
    mock_phone.e164 = "+391234567890"
    mock_phone.user = mock_user

    mock_routing = MagicMock(spec=AgentRouting)
    mock_routing.agent_id = "agent_123"
    mock_routing.is_active = True

    def query_side_effect(model):
        query = MagicMock()
        if model == PhoneNumber:
            query.filter.return_value.first.return_value = mock_phone
        elif model == AgentRouting:
            query.filter.return_value.first.return_value = mock_routing
        return query

    mock_db.query.side_effect = query_side_effect

    app.dependency_overrides[get_db] = lambda: mock_db
    try:
        with patch("app.validate_twilio_signature", new=AsyncMock(return_value=True)):
            response = client.post(
                "/twilio/voice",
                data={"To": "+391234567890", "From": "+390000000000", "CallSid": "CA123"},
            )
    finally:
        app.dependency_overrides.pop(get_db, None)

    assert response.status_code == 200
    assert response.headers["content-type"] == "application/xml"
