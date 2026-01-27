
import os
import hmac
import hashlib
import base64
import time
import json
from unittest.mock import patch, MagicMock
from fastapi.testclient import TestClient
from app import app
from auth import verify_elevenlabs_signature

client = TestClient(app)

SECRET = "test_secret_123"

def generate_signature(secret, body, timestamp, flavor="default", encoding="hex"):
    secret_bytes = secret.encode("utf-8")
    timestamp_bytes = str(timestamp).encode("utf-8")

    if flavor == "default":
        payload = body + timestamp_bytes
    elif flavor == "reverse":
        payload = timestamp_bytes + body
    elif flavor == "dotted":
        payload = timestamp_bytes + b"." + body
    else:
        raise ValueError("Unknown flavor")

    h = hmac.new(secret_bytes, payload, hashlib.sha256)

    if encoding == "hex":
        return h.hexdigest()
    elif encoding == "base64":
        return base64.b64encode(h.digest()).decode("utf-8")
    elif encoding == "base64_urlsafe":
        return base64.urlsafe_b64encode(h.digest()).decode("utf-8")
    elif encoding == "base64_nopad":
        return base64.b64encode(h.digest()).decode("utf-8").rstrip("=")
    elif encoding == "base64_urlsafe_nopad":
        return base64.urlsafe_b64encode(h.digest()).decode("utf-8").rstrip("=")
    else:
        raise ValueError("Unknown encoding")

def test_webhook_missing_secret_config():
    """If env var is not set, it should allow requests (legacy behavior) or logic dictates."""
    with patch.dict(os.environ, {}, clear=True):
        response = client.post("/elevenlabs/webhook", json={"type": "ping"})
        assert response.status_code == 500
        assert response.json().get("detail") == "Server misconfiguration"

def test_webhook_no_header():
    with patch.dict(os.environ, {"ELEVENLABS_WEBHOOK_SECRET": SECRET}):
        response = client.post("/elevenlabs/webhook", json={"type": "ping"})
        # Requirement changed: If header missing, log warning and continue (200)
        assert response.status_code == 200

def test_webhook_invalid_signature():
    with patch.dict(os.environ, {"ELEVENLABS_WEBHOOK_SECRET": SECRET}):
        headers = {"elevenlabs-signature": "t=123456,v1=invalid_sig"}
        response = client.post("/elevenlabs/webhook", json={"type": "ping"}, headers=headers)
        assert response.status_code == 403

def test_webhook_valid_signature_ignored_type():
    with patch.dict(os.environ, {"ELEVENLABS_WEBHOOK_SECRET": SECRET}):
        payload_dict = {"type": "ping", "data": {}}
        payload_bytes = json.dumps(payload_dict).encode("utf-8")

        # Using default hex signature
        ts = str(int(time.time()))
        sig = generate_signature(SECRET, payload_bytes, ts)
        headers = {"elevenlabs-signature": f"t={ts},v1={sig}"}

        response = client.post(
            "/elevenlabs/webhook",
            content=payload_bytes,
            headers=headers
        )

        assert response.status_code == 200
        assert response.json()["status"] == "ignored"

def test_webhook_success():
    with patch.dict(os.environ, {"ELEVENLABS_WEBHOOK_SECRET": SECRET}):
        with patch("app.get_queue") as mock_get_queue, \
             patch("app.SessionLocal") as mock_session_cls:

            mock_queue = MagicMock()
            mock_get_queue.return_value = mock_queue

            mock_session = MagicMock()
            mock_session_cls.return_value.__enter__.return_value = mock_session
            mock_session.query.return_value.filter.return_value.first.return_value = None

            payload_dict = {"type": "post_call_transcription", "data": {"agent_id": "test"}}
            payload_bytes = json.dumps(payload_dict).encode("utf-8")

            ts = str(int(time.time()))
            sig = generate_signature(SECRET, payload_bytes, ts)
            headers = {"elevenlabs-signature": f"t={ts},v1={sig}"}

            response = client.post(
                "/elevenlabs/webhook",
                content=payload_bytes,
                headers=headers
            )

            assert response.status_code == 200
            assert response.json()["status"] == "ok"
            mock_queue.enqueue.assert_called_once()

# --- Unit Tests for verify_elevenlabs_signature ---

def test_verify_missing_header():
    assert verify_elevenlabs_signature(b"body", {}, SECRET) is None

def test_verify_valid_hex_default():
    body = b"test_body"
    ts = "1234567890"
    sig = generate_signature(SECRET, body, ts, "default", "hex")
    headers = {"elevenlabs-signature": f"t={ts},v1={sig}"}
    assert verify_elevenlabs_signature(body, headers, SECRET) is True

def test_verify_valid_base64_reverse():
    body = b"test_body"
    ts = "1234567890"
    sig = generate_signature(SECRET, body, ts, "reverse", "base64")
    headers = {"elevenlabs-signature": f"t={ts},v1={sig}"}
    assert verify_elevenlabs_signature(body, headers, SECRET) is True

def test_verify_valid_base64_urlsafe_dotted():
    body = b"test_body"
    ts = "1234567890"
    sig = generate_signature(SECRET, body, ts, "dotted", "base64_urlsafe")
    headers = {"elevenlabs-signature": f"t={ts},v1={sig}"}
    assert verify_elevenlabs_signature(body, headers, SECRET) is True

def test_verify_valid_base64_nopad():
    body = b"test_body_padding_check"
    ts = "1234567890"
    # Ensure it needs padding normally
    sig = generate_signature(SECRET, body, ts, "default", "base64_nopad")
    headers = {"elevenlabs-signature": f"t={ts},v1={sig}"}
    assert verify_elevenlabs_signature(body, headers, SECRET) is True

def test_verify_whitespace_header():
    body = b"test_body"
    ts = "1234567890"
    sig = generate_signature(SECRET, body, ts, "default", "hex")
    # Spaces around comma and equals
    headers = {"elevenlabs-signature": f" t = {ts} , v1 = {sig} "}
    assert verify_elevenlabs_signature(body, headers, SECRET) is True

def test_verify_alt_header_key():
    body = b"test_body"
    ts = "1234567890"
    sig = generate_signature(SECRET, body, ts, "default", "hex")
    headers = {"X-Elevenlabs-Signature": f"t={ts},v1={sig}"}
    assert verify_elevenlabs_signature(body, headers, SECRET) is True

def test_verify_invalid_signature():
    body = b"test_body"
    ts = "1234567890"
    sig = "invalid_signature"
    headers = {"elevenlabs-signature": f"t={ts},v1={sig}"}
    assert verify_elevenlabs_signature(body, headers, SECRET) is False

def test_verify_invalid_header_format():
    body = b"test_body"
    headers = {"elevenlabs-signature": "invalid_format"}
    assert verify_elevenlabs_signature(body, headers, SECRET) is False
