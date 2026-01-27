
import os
import hmac
import hashlib
import time
import json
from unittest.mock import patch, MagicMock
from fastapi.testclient import TestClient
from app import app

client = TestClient(app)

SECRET = "test_secret_123"

def generate_signature(secret: str, body: bytes, timestamp: str = None) -> dict:
    if timestamp is None:
        timestamp = str(int(time.time()))

    payload = body + timestamp.encode("utf-8")
    signature = hmac.new(
        secret.encode("utf-8"),
        payload,
        hashlib.sha256
    ).hexdigest()

    return {
        "elevenlabs-signature": f"t={timestamp},v1={signature}"
    }

def test_webhook_missing_secret_config():
    """If env var is not set, it should allow requests (legacy behavior) or logic dictates."""
    # The current implementation checks: `secret = os.getenv(...)` then `if secret: ...`
    # So if secret is missing, it skips verification.
    with patch.dict(os.environ, {}, clear=True):
        # We need to make sure ELEVENLABS_WEBHOOK_SECRET is NOT in env
        # Note: os.environ patch might not affect app.py if it reads at module level?
        # app.py reads it inside the function: `secret = os.getenv("ELEVENLABS_WEBHOOK_SECRET")`
        # So patch.dict should work.

        response = client.post("/elevenlabs/webhook", json={"type": "ping"})
        # Should NOT be 401. Likely 200 (ignored) or 200 (ok).
        assert response.status_code == 200
        assert response.json().get("status") == "ignored"

def test_webhook_no_header():
    with patch.dict(os.environ, {"ELEVENLABS_WEBHOOK_SECRET": SECRET}):
        response = client.post("/elevenlabs/webhook", json={"type": "ping"})
        assert response.status_code == 403

def test_webhook_invalid_signature():
    with patch.dict(os.environ, {"ELEVENLABS_WEBHOOK_SECRET": SECRET}):
        headers = {"elevenlabs-signature": "t=123456,v1=invalid_sig"}
        response = client.post("/elevenlabs/webhook", json={"type": "ping"}, headers=headers)
        assert response.status_code == 403

def test_webhook_valid_signature_ignored_type():
    with patch.dict(os.environ, {"ELEVENLABS_WEBHOOK_SECRET": SECRET}):
        payload_dict = {"type": "ping", "data": {}} # 'ping' is not a valid type in logic, so it returns ignored
        payload_bytes = json.dumps(payload_dict).encode("utf-8")

        headers = generate_signature(SECRET, payload_bytes)

        response = client.post(
            "/elevenlabs/webhook",
            content=payload_bytes,
            headers=headers
        )

        assert response.status_code == 200
        # The endpoint returns {status: ignored, reason: unsupported type ping}
        assert response.json()["status"] == "ignored"

def test_webhook_success():
    with patch.dict(os.environ, {"ELEVENLABS_WEBHOOK_SECRET": SECRET}):
        with patch("app.get_queue") as mock_get_queue, \
             patch("app.SessionLocal") as mock_session_cls:

            mock_queue = MagicMock()
            mock_get_queue.return_value = mock_queue

            # Mock DB Session to return None for queries (simulate unknown agent)
            mock_session = MagicMock()
            mock_session_cls.return_value.__enter__.return_value = mock_session
            # Default mock return is MagicMock, so filter().first() will return MagicMock
            # We want it to return None to simulate "Not found"
            mock_session.query.return_value.filter.return_value.first.return_value = None

            payload_dict = {"type": "post_call_transcription", "data": {"agent_id": "test"}}
            payload_bytes = json.dumps(payload_dict).encode("utf-8")
            headers = generate_signature(SECRET, payload_bytes)

            response = client.post(
                "/elevenlabs/webhook",
                content=payload_bytes,
                headers=headers
            )

            assert response.status_code == 200
            assert response.json()["status"] == "ok"
            mock_queue.enqueue.assert_called_once()
