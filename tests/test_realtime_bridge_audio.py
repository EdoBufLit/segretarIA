import base64
import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from services.realtime_bridge import RealtimeSession


@pytest.mark.asyncio
async def test_twilio_audio_forwarded_as_mulaw_chunk():
    async def iter_text():
        yield json.dumps({
            "event": "start",
            "start": {"streamSid": "SS123", "callSid": "CA123"},
        })
        payload = base64.b64encode(b"raw").decode("utf-8")
        yield json.dumps({
            "event": "media",
            "media": {"payload": payload},
        })
        yield json.dumps({"event": "stop"})

    twilio_ws = MagicMock()
    twilio_ws.iter_text = iter_text

    session = RealtimeSession(twilio_ws, "agent-1")
    session.eleven_ws = AsyncMock()

    with patch.object(session, "_to_mulaw_8k", return_value=b"mulaw") as mock_convert, \
        patch("realtime.session.CallSessionManager") as mock_mgr:
        mock_mgr.return_value.update_stream_sid = MagicMock()
        mock_mgr.return_value.update_status = MagicMock()

        await session.handle_twilio_messages()

    mock_convert.assert_called_once()
    session.eleven_ws.send.assert_called_once()
    sent_payload = json.loads(session.eleven_ws.send.call_args[0][0])
    assert sent_payload["user_audio_chunk"] == base64.b64encode(b"mulaw").decode("utf-8")
