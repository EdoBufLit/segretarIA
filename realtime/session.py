import asyncio
import base64
import io
import json
import logging
import os
import time
from typing import Dict, Optional

try:
    import audioop
except ImportError:
    import audioop_lts as audioop
import websockets
from websockets.exceptions import ConnectionClosedError, ConnectionClosedOK
from fastapi import WebSocket, WebSocketDisconnect
from pydub import AudioSegment

from services.call_session import CallSessionManager, CallStatus

logger = logging.getLogger("app.services.realtime_bridge")

# Registry of active sessions by CallSid
active_sessions: Dict[str, "RealtimeSession"] = {}


async def terminate_session(call_sid: str):
    """
    Terminates the WebSocket session for a given CallSid.

    By closing the WebSocket, we gracefully end the Media Stream on our end.
    However, to ensure the call doesn't hang up or just fall through,
    the caller (barge-in endpoint) must concurrently issue a Twilio Client update()
    to redirect the CallSid to a new TwiML URL.

    This works because Twilio Media Streams are just TwiML verbs (<Connect><Stream>).
    Updating the call via API replaces the current executing TwiML with the new one,
    effectively "breaking" the stream connection and re-routing the call.
    """
    session = active_sessions.get(call_sid)
    if session:
        logger.info(f"Terminating session for {call_sid}")
        await session.close()
    else:
        logger.warning(f"Attempted to terminate non-existent session {call_sid}")


class RealtimeSession:
    """
    Manages the bi-directional audio bridge between Twilio Media Streams and ElevenLabs Realtime (ConvAI).
    Handles transcoding between Twilio (G.711 mulaw, 8000Hz) and ElevenLabs (mulaw, 8000Hz).
    """
    def __init__(self, twilio_ws: WebSocket, agent_id: str, initial_start_message: Dict = None):
        self.twilio_ws = twilio_ws
        self.agent_id = agent_id
        self.initial_start_message = initial_start_message
        self.stream_sid: Optional[str] = None
        self.call_sid: Optional[str] = None
        self.eleven_ws = None
        self.is_open = True
        self.tasks = set()

        # Audio Transcoding State
        # EL (16k) -> Twilio (8k)
        self.out_rate_state = None

        # Stats
        self.frames_in = 0
        self.frames_out = 0
        self.start_time = time.time()
        self.conn_start_perf = time.perf_counter()

        # Latency tracking
        self.first_twilio_media_ts: Optional[float] = None
        self.first_eleven_audio_ts: Optional[float] = None
        self.eleven_response_warning_task: Optional[asyncio.Task] = None
        self.first_eleven_request_ts: Optional[float] = None
        self.first_twilio_send_ts: Optional[float] = None
        self.first_eleven_audio_perf: Optional[float] = None

    async def start(self):
        """
        Starts the bridge session.
        """
        api_key = os.getenv("ELEVEN_API_KEY")
        if not api_key:
            logger.error("ELEVEN_API_KEY not configured.")
            await self.close()
            return

        try:
            # 1. Connect to ElevenLabs
            # Note: ElevenLabs usually defaults to 16kHz PCM for ConvAI unless configured otherwise.
            url = f"wss://api.elevenlabs.io/v1/convai/conversation?agent_id={self.agent_id}"
            headers = {"xi-api-key": api_key}

            logger.info(f"Connecting to ElevenLabs agent {self.agent_id}...")

            async with websockets.connect(url, additional_headers=headers) as eleven_ws:
                self.eleven_ws = eleven_ws
                logger.info("Connected to ElevenLabs.")

                # 2. Start concurrent tasks for reading from both sides
                twilio_task = asyncio.create_task(self.handle_twilio_messages())
                eleven_task = asyncio.create_task(self.handle_eleven_messages())

                self.tasks.add(twilio_task)
                self.tasks.add(eleven_task)

                # Clean up task references when done
                twilio_task.add_done_callback(self.tasks.discard)
                eleven_task.add_done_callback(self.tasks.discard)

                # Wait for either to finish (likely due to close/error)
                try:
                    await asyncio.wait(
                        [twilio_task, eleven_task],
                        return_when=asyncio.FIRST_COMPLETED
                    )
                except asyncio.CancelledError:
                    logger.info("RealtimeSession cancelled.")
                finally:
                    # Logic is handled in close(), but we can ensure tasks are cancelled here if not already
                    pass

        except Exception as e:
            logger.error(f"Error in RealtimeSession: {e}")
        finally:
            await self.close()

    async def handle_twilio_messages(self):
        """
        Reads messages from Twilio WebSocket, transcodes audio, and forwards to ElevenLabs.
        Twilio: mulaw 8000Hz -> ElevenLabs: mulaw 8000Hz
        """
        try:
            # Process initial message if provided (consumed before session start)
            if self.initial_start_message:
                if await self._process_twilio_message(self.initial_start_message):
                    return

            async for message in self.twilio_ws.iter_text():
                data = json.loads(message)
                if await self._process_twilio_message(data):
                    break

        except WebSocketDisconnect:
            logger.info("Twilio WebSocket disconnected.")
        except asyncio.CancelledError:
            # Expected during shutdown
            raise
        except Exception as e:
            logger.error(f"Error handling Twilio messages: {e}")
            raise

    async def _process_twilio_message(self, data: Dict) -> bool:
        """
        Internal handler for a single Twilio message.
        Returns True if the stream should stop (e.g. 'stop' event).
        """
        event_type = data.get("event")

        if event_type == "start":
            self.stream_sid = data.get("start", {}).get("streamSid")
            call_sid = data.get("start", {}).get("callSid")
            self.call_sid = call_sid

            # Register session
            active_sessions[call_sid] = self

            # Update Call Session
            try:
                mgr = CallSessionManager()
                mgr.update_stream_sid(call_sid, self.stream_sid)
                mgr.update_status(call_sid, CallStatus.AI_ACTIVE)
            except Exception as e:
                logger.error(f"Failed to update call session for {call_sid}: {e}")

            logger.info(json.dumps({
                "event": "twilio_stream_start",
                "streamSid": self.stream_sid,
                "callSid": call_sid,
                "agent_id": self.agent_id
            }))

        elif event_type == "media":
            if self.eleven_ws:
                payload_b64 = data.get("media", {}).get("payload")
                if payload_b64:
                    self.frames_in += 1
                    self._maybe_log_first_twilio_media()

                    # 1. Decode base64
                    chunk = base64.b64decode(payload_b64)

                    # 2. Ensure mulaw 8k encoding for ElevenLabs
                    out_b64 = base64.b64encode(self._to_mulaw_8k(chunk)).decode("utf-8")

                    # 3. Send to ElevenLabs
                    if self.first_eleven_request_ts is None:
                        self.first_eleven_request_ts = time.perf_counter()
                        self._log_step("Inizio richiesta a ElevenLabs (invio audio)", 0)
                    msg = {
                        "user_audio_chunk": out_b64
                    }
                    send_start = time.perf_counter()
                    await self.eleven_ws.send(json.dumps(msg))
                    send_ms = (time.perf_counter() - send_start) * 1000
                    if self.frames_in == 1:
                        self._log_step("Invio audio a ElevenLabs", send_ms)

        elif event_type == "stop":
            logger.info("Twilio stream stopped.")
            return True

        return False

    async def handle_eleven_messages(self):
        """
        Reads messages from ElevenLabs WebSocket, transcodes audio, and forwards to Twilio.
        ElevenLabs: PCM 16000Hz -> Twilio: mulaw 8000Hz
        """
        try:
            async for message in self.eleven_ws:
                data = json.loads(message)
                msg_type = data.get("type")

                if msg_type == "audio":
                    audio_event = data.get("audio_event", {})
                    payload_b64 = audio_event.get("audio_base_64")

                    if payload_b64 and self.stream_sid:
                        self.frames_out += 1
                        self._maybe_log_first_eleven_audio()

                        # 1. Decode base64
                        chunk = base64.b64decode(payload_b64)

                        # 2. Resample: 16k -> 8k
                        pcm_8k, self.out_rate_state = audioop.ratecv(
                            chunk, 2, 1, 16000, 8000, self.out_rate_state
                        )

                        # 3. Encode: PCM 16-bit 8k -> mulaw 8k
                        ulaw_8k = audioop.lin2ulaw(pcm_8k, 2)

                        # 4. Encode base64
                        out_b64 = base64.b64encode(ulaw_8k).decode("utf-8")

                        # 5. Send to Twilio
                        response = {
                            "event": "media",
                            "streamSid": self.stream_sid,
                            "media": {
                                "payload": out_b64
                            }
                        }
                        send_start = time.perf_counter()
                        await self.twilio_ws.send_text(json.dumps(response))
                        send_ms = (time.perf_counter() - send_start) * 1000
                        if self.frames_out == 1:
                            self._log_step("Audio inviato via WebSocket", send_ms)
                            if self.first_eleven_audio_perf is not None:
                                response_ms = (time.perf_counter() - self.first_eleven_audio_perf) * 1000
                                self._log_step("Risposta ElevenLabs ricevuta (fine)", response_ms)

                elif msg_type == "interruption":
                    if self.stream_sid:
                        await self.twilio_ws.send_text(json.dumps({
                            "event": "clear",
                            "streamSid": self.stream_sid
                        }))

                elif msg_type == "ping":
                    pass

        except ConnectionClosedOK:
            logger.info("ElevenLabs WebSocket closed normally.")
        except ConnectionClosedError as exc:
            logger.warning(f"ElevenLabs WebSocket closed with error: code={exc.code} reason={exc.reason}")
        except asyncio.CancelledError:
            # Expected during shutdown
            raise
        except Exception as e:
            logger.error(f"Error handling ElevenLabs messages: {e}")
            raise

    def _maybe_log_first_twilio_media(self):
        if self.first_twilio_media_ts is not None:
            return
        self.first_twilio_media_ts = time.monotonic()
        self._log_step("Ricezione primo pacchetto audio via WebSocket", 0)
        self._schedule_eleven_response_warning()

    def _maybe_log_first_eleven_audio(self):
        if self.first_eleven_audio_ts is not None:
            return
        self.first_eleven_audio_ts = time.monotonic()
        self.first_eleven_audio_perf = time.perf_counter()
        delay_ms = None
        if self.first_twilio_media_ts is not None:
            delay_ms = int((self.first_eleven_audio_ts - self.first_twilio_media_ts) * 1000)
        self._log_step("Risposta ElevenLabs ricevuta (inizio)", delay_ms or 0)
        if self.eleven_response_warning_task and not self.eleven_response_warning_task.done():
            self.eleven_response_warning_task.cancel()

    def _schedule_eleven_response_warning(self):
        if self.eleven_response_warning_task:
            return
        self.eleven_response_warning_task = asyncio.create_task(self._warn_if_no_eleven_audio())

    async def _warn_if_no_eleven_audio(self):
        try:
            await asyncio.sleep(3)
            if self.first_eleven_audio_ts is None:
                elapsed_ms = None
                if self.first_twilio_media_ts is not None:
                    elapsed_ms = int((time.monotonic() - self.first_twilio_media_ts) * 1000)
                self._log_step("ElevenLabs audio non ricevuto entro 3s", elapsed_ms or 0, level="warning")
        except asyncio.CancelledError:
            return

    def _to_mulaw_8k(self, mulaw_8k: bytes) -> bytes:
        """
        Ensures audio bytes are encoded as 8-bit mu-law at 8000 Hz using pydub/ffmpeg.
        """
        try:
            pcm_8k = audioop.ulaw2lin(mulaw_8k, 2)
            segment = AudioSegment(
                data=pcm_8k,
                sample_width=2,
                frame_rate=8000,
                channels=1,
            )
            segment = segment.set_frame_rate(8000).set_sample_width(1).set_channels(1)
            buffer = io.BytesIO()
            segment.export(buffer, format="wav", codec="pcm_mulaw")
            return buffer.getvalue()
        except Exception as exc:
            logger.error("Failed to convert audio to mulaw 8k: %s", exc)
            return mulaw_8k

    async def close(self):
        """
        Closes the session cleanly. Idempotent.
        """
        if not self.is_open:
            return

        self.is_open = False

        if self.eleven_response_warning_task and not self.eleven_response_warning_task.done():
            self.eleven_response_warning_task.cancel()

        # Unregister
        if self.call_sid and self.call_sid in active_sessions:
            del active_sessions[self.call_sid]
        duration_ms = int((time.time() - self.start_time) * 1000)
        conn_duration_ms = (time.perf_counter() - self.conn_start_perf) * 1000
        self._log_step("Durata connessione WebSocket (accept→close)", conn_duration_ms)

        # Log session closed with stats
        log_data = {
            "event": "session_closed",
            "agent_id": self.agent_id,
            "call_sid": self.stream_sid,
            "frames_in": self.frames_in,
            "frames_out": self.frames_out,
            "duration_ms": duration_ms
        }
        logger.info(json.dumps(log_data))

        # Cleanup Call Session
        if self.call_sid:
            try:
                mgr = CallSessionManager()
                current_session = mgr.get_session(self.call_sid)
                # Only end session if it's not transitioning to human
                if current_session and current_session.get("status") != CallStatus.HUMAN_REQUESTED:
                    mgr.end_session(self.call_sid)
            except Exception as e:
                logger.error(f"Failed to end session for {self.call_sid}: {e}")

        # Cancel all running tasks and await them to avoid unhandled exceptions
        pending_tasks = []
        for task in self.tasks:
            if not task.done():
                task.cancel()
                pending_tasks.append(task)
        if pending_tasks:
            try:
                await asyncio.gather(*pending_tasks, return_exceptions=True)
            except Exception as exc:
                logger.debug(f"Error while awaiting cancelled tasks: {exc}")

        # Explicitly close WebSockets
        if self.eleven_ws:
            try:
                await self.eleven_ws.close()
            except Exception:
                pass  # Ignore errors during close

        if self.twilio_ws:
            try:
                # 1000 = Normal Closure
                await self.twilio_ws.close(code=1000)
            except Exception:
                pass  # Ignore if already closed

    def _log_step(self, message: str, duration_ms: float, level: str = "info"):
        lag = " (LAG!)" if duration_ms > 500 else ""
        log_message = f"{message} | duration: {duration_ms:.0f}ms{lag}"
        if level == "warning":
            logger.warning(log_message)
        else:
            logger.info(log_message)
