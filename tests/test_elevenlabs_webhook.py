
import os
import hmac
import hashlib
import time
import json
from unittest.mock import patch
from fastapi.testclient import TestClient
from app import app

client = TestClient(app)

SECRET = "test_secret_123"

def generate_signature(secret: str, body: bytes, timestamp: str = None) -> dict:
    if timestamp is None:
        timestamp = str(int(time.time()))

    payload = f"{timestamp}.".encode("utf-8") + body
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
        assert response.status_code == 401

def test_webhook_invalid_signature():
    with patch.dict(os.environ, {"ELEVENLABS_WEBHOOK_SECRET": SECRET}):
        headers = {"elevenlabs-signature": "t=123456,v1=invalid_sig"}
        response = client.post("/elevenlabs/webhook", json={"type": "ping"}, headers=headers)
        assert response.status_code == 401

def test_webhook_valid_signature():
    with patch.dict(os.environ, {"ELEVENLABS_WEBHOOK_SECRET": SECRET}):
        payload_dict = {"type": "ping", "data": {}} # 'ping' is not a valid type in logic, so it returns ignored
        payload_bytes = json.dumps(payload_dict).encode("utf-8")

        headers = generate_signature(SECRET, payload_bytes)

        # We must send bytes manually or let client serialize, but we need exact bytes for sig
        # TestClient json=... serializes with no spaces usually?
        # Safest is to use content=...

        response = client.post(
            "/elevenlabs/webhook",
            content=payload_bytes,
            headers=headers
        )

        assert response.status_code == 200
        # The endpoint returns {status: ignored, reason: unsupported type ping}
        assert response.json()["status"] == "ignored"
