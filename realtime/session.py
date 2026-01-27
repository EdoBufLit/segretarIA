import asyncio
import base64
import io
import json
import logging
import os
import time
from typing import Dict, Optional

import audioop
import websockets
from websockets.exceptions import ConnectionClosedOK, ConnectionClosedError
from fastapi import WebSocket, WebSocketDisconnect

from services.call_session import CallSessionManager, CallStatus
from services.timing import log_duration

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
        self.is_closing = False
        self.tasks = set()

        # Audio Transcoding State
        # EL (16k) -> Twilio (8k)
        self.out_rate_state = None

        # Stats
        self.frames_in = 0
        self.frames_out = 0
        self.start_time = time.time()

        # Latency tracking (legacy)
        self.first_twilio_media_ts: Optional[float] = None
        self.first_eleven_audio_ts: Optional[float] = None
        self.eleven_response_warning_task: Optional[asyncio.Task] = None

        # Precise Latency Instrumentation (ms)
        self.call_start_ts: Optional[float] = None
        self.first_twilio_audio_ts: Optional[float] = None
        self.first_audio_sent_to_eleven_ts: Optional[float] = None
        self.first_audio_from_eleven_ts: Optional[float] = None

        # Latency Debug Timings
        self.t_ws_eleven_open: Optional[float] = None
        self.t_first_chunk_sent_to_eleven: Optional[float] = None
        self.t_first_msg_from_eleven: Optional[float] = None
        self.t_first_audio_from_eleven: Optional[float] = None

    async def start(self):
        """
        Starts the bridge session.
        """
        # Record start timestamp for latency calculation
        self.call_start_ts = time.monotonic() * 1000

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
                self.t_ws_eleven_open = time.time()
                logger.info(f"Connected to ElevenLabs. t_ws_eleven_open={self.t_ws_eleven_open}")

                # 2. Start concurrent tasks for reading from both sides
                twilio_task = asyncio.create_task(self.handle_twilio_messages())
                eleven_task = asyncio.create_task(self.handle_eleven_messages())

                self.tasks.add(twilio_task)
                self.tasks.add(eleven_task)

                # DO NOT remove from self.tasks on completion immediately
                # to allow close() to await them and retrieve exceptions.

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
                # [LATENCY] 1. First audio received from Twilio
                if self.first_twilio_audio_ts is None:
                    self.first_twilio_audio_ts = time.monotonic() * 1000
                    logger.info(f"[LATENCY] t0 first_audio_from_twilio = {self.first_twilio_audio_ts:.2f}ms")

                payload_b64 = data.get("media", {}).get("payload")
                if payload_b64:
                    self.frames_in += 1
                    self._maybe_log_first_twilio_media()

                    # 1. Decode base64 to bytes chunk
                    chunk = base64.b64decode(payload_b64)

                    # 2. DO NOT TRANSCODE. Re-encode chunk directly.
                    # Twilio sends mulaw 8k. ElevenLabs expects mulaw 8k.
                    # Previous logic using pydub/ffmpeg was converting to WAV which adds header overhead and latency.
                    out_b64 = base64.b64encode(chunk).decode("utf-8")

                    # 3. Send to ElevenLabs
                    msg = {
                        "user_audio_chunk": out_b64
                    }

                    # [LATENCY] 2. First audio forwarded to ElevenLabs
                    if self.first_audio_sent_to_eleven_ts is None:
                        self.first_audio_sent_to_eleven_ts = time.monotonic() * 1000
                        self.t_first_chunk_sent_to_eleven = time.time()
                        logger.info(f"[LATENCY] t1 first_audio_sent_to_eleven = {self.first_audio_sent_to_eleven_ts:.2f}ms")
                        logger.info(f"t_first_chunk_sent_to_eleven={self.t_first_chunk_sent_to_eleven}")

                    await self.eleven_ws.send(json.dumps(msg))

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
                if self.t_first_msg_from_eleven is None:
                    self.t_first_msg_from_eleven = time.time()
                    logger.info(f"t_first_msg_from_eleven={self.t_first_msg_from_eleven}")

                data = json.loads(message)
                msg_type = data.get("type")

                if msg_type == "audio":
                    if self.t_first_audio_from_eleven is None:
                        self.t_first_audio_from_eleven = time.time()
                        logger.info(f"t_first_audio_from_eleven={self.t_first_audio_from_eleven}")

                    audio_event = data.get("audio_event", {})
                    payload_b64 = audio_event.get("audio_base_64")

                    if payload_b64 and self.stream_sid:
                        self.frames_out += 1

                        # [LATENCY] 3. First audio received from ElevenLabs
                        if self.first_audio_from_eleven_ts is None:
                            self.first_audio_from_eleven_ts = time.monotonic() * 1000
                            logger.info(f"[LATENCY] t2 first_audio_from_eleven = {self.first_audio_from_eleven_ts:.2f}ms")

                            # [LATENCY] 4. Compute and log latencies
                            if self.call_start_ts and self.first_twilio_audio_ts and self.first_audio_sent_to_eleven_ts:
                                t0_delta = self.first_twilio_audio_ts - self.call_start_ts
                                t1_delta = self.first_audio_sent_to_eleven_ts - self.first_twilio_audio_ts
                                t2_delta = self.first_audio_from_eleven_ts - self.first_audio_sent_to_eleven_ts
                                total_latency = self.first_audio_from_eleven_ts - self.first_twilio_audio_ts

                                logger.info(f"[LATENCY] Twilio→Server: {t0_delta:.2f}ms")
                                logger.info(f"[LATENCY] Server→Eleven: {t1_delta:.2f}ms")
                                logger.info(f"[LATENCY] Eleven processing: {t2_delta:.2f}ms")
                                logger.info(f"[LATENCY] End-to-end audio latency: {total_latency:.2f}ms")

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

                        # Logging audio send latency
                        with log_duration("Audio inviato via WebSocket"):
                            await self.twilio_ws.send_text(json.dumps(response))

                elif msg_type == "interruption":
                    if self.stream_sid:
                        await self.twilio_ws.send_text(json.dumps({
                            "event": "clear",
                            "streamSid": self.stream_sid
                        }))

                elif msg_type == "ping":
                    pass

        except ConnectionClosedOK:
            logger.info("ElevenLabs WebSocket closed normally (1000).")
        except ConnectionClosedError as e:
            logger.warning(f"ElevenLabs WebSocket closed with error: code={e.code}, reason={e.reason}")
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

        # DIAGNOSIS LOG
        logging.info("Ricezione primo pacchetto audio via WebSocket | duration: 0ms")

        self._schedule_eleven_response_warning()

    def _maybe_log_first_eleven_audio(self):
        if self.first_eleven_audio_ts is not None:
            return
        self.first_eleven_audio_ts = time.monotonic()

        # Calculate Latency
        if self.first_twilio_media_ts is not None:
            delay_ms = int((self.first_eleven_audio_ts - self.first_twilio_media_ts) * 1000)
            logging.info(f"Latenza totale audio (audio_in→audio_out) | duration: {delay_ms}ms")
        else:
            logging.info("Risposta ElevenLabs ricevuta (primo audio) | duration: 0ms")

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
                logger.warning(json.dumps({
                    "event": "elevenlabs_first_audio_timeout",
                    "callSid": self.call_sid,
                    "streamSid": self.stream_sid,
                    "elapsed_ms": elapsed_ms
                }))
        except asyncio.CancelledError:
            return

    # _to_mulaw_8k removed as per optimization request

    async def close(self):
        """
        Closes the session cleanly. Idempotent.
        """
        if self.is_closing or not self.is_open:
            return

        self.is_closing = True
        self.is_open = False

        if self.eleven_response_warning_task and not self.eleven_response_warning_task.done():
            self.eleven_response_warning_task.cancel()

        # Unregister
        if self.call_sid and self.call_sid in active_sessions:
            del active_sessions[self.call_sid]
        duration_ms = int((time.time() - self.start_time) * 1000)

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

        # Cancel all running tasks
        for task in list(self.tasks):
            if not task.done():
                task.cancel()

        # Ensure tasks are awaited to prevent "Task exception was never retrieved"
        if self.tasks:
            try:
                await asyncio.gather(*self.tasks, return_exceptions=True)
            except Exception as e:
                logger.warning(f"Error awaiting cancelled tasks: {e}")
            finally:
                self.tasks.clear()

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
