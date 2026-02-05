import base64
import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from services.realtime_bridge import RealtimeSession


@pytest.mark.asyncio
async def test_twilio_audio_forwarded_as_mulaw_chunk():
    input_bytes = b"raw_audio_bytes"
    input_b64 = base64.b64encode(input_bytes).decode("utf-8")

    async def iter_text():
        yield json.dumps({
            "event": "start",
            "start": {"streamSid": "SS123", "callSid": "CA123"},
        })
        yield json.dumps({
            "event": "media",
            "media": {"payload": input_b64},
        })
        yield json.dumps({"event": "stop"})

    twilio_ws = MagicMock()
    twilio_ws.iter_text = iter_text

    session = RealtimeSession(twilio_ws, "agent-1")
    session.eleven_ws = AsyncMock()

    # We no longer mock _to_mulaw_8k as it is removed
    with patch("realtime.session.CallSessionManager") as mock_mgr:
        mock_mgr.return_value.update_stream_sid = MagicMock()
        mock_mgr.return_value.update_status = MagicMock()

        await session.handle_twilio_messages()

    session.eleven_ws.send.assert_called_once()
    sent_payload = json.loads(session.eleven_ws.send.call_args[0][0])

    # Assert that the payload sent to ElevenLabs is the same as received (just re-encoded)
    assert sent_payload["user_audio_chunk"] == input_b64
