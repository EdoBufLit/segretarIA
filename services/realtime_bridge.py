import json
import base64
import asyncio
import logging
import websockets
import os
try:
    import audioop
except ImportError:
    import audioop_lts as audioop
import time
from fastapi import WebSocket, WebSocketDisconnect
from services.call_session import CallSessionManager, CallStatus
from typing import Dict

logger = logging.getLogger("app.services.realtime_bridge")

# Registry of active sessions by CallSid
active_sessions: Dict[str, "RealtimeSession"] = {}

async def terminate_session(call_sid: str):
    """
    Terminates the WebSocket session for a given CallSid.
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
    Handles transcoding between Twilio (G.711 mulaw, 8000Hz) and ElevenLabs (PCM, 16000Hz).
    """
    def __init__(self, twilio_ws: WebSocket, agent_id: str):
        self.twilio_ws = twilio_ws
        self.agent_id = agent_id
        self.stream_sid = None
        self.call_sid = None
        self.eleven_ws = None
        self.is_open = True
        self.tasks = set()

        # Audio Transcoding State
        # Twilio (8k) -> EL (16k)
        self.in_rate_state = None
        # EL (16k) -> Twilio (8k)
        self.out_rate_state = None

        # Stats
        self.frames_in = 0
        self.frames_out = 0
        self.start_time = time.time()

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

            async with websockets.connect(url, extra_headers=headers) as eleven_ws:
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
                    done, pending = await asyncio.wait(
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
        Twilio: mulaw 8000Hz -> ElevenLabs: PCM 16000Hz
        """
        try:
            async for message in self.twilio_ws.iter_text():
                data = json.loads(message)
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
                            # 1. Decode base64
                            chunk = base64.b64decode(payload_b64)

                            # 2. Transcode: mulaw 8k -> PCM 16-bit 8k
                            # width=2 means 16-bit
                            pcm_8k = audioop.ulaw2lin(chunk, 2)

                            # 3. Resample: 8k -> 16k
                            pcm_16k, self.in_rate_state = audioop.ratecv(
                                pcm_8k, 2, 1, 8000, 16000, self.in_rate_state
                            )

                            # 4. Encode base64
                            out_b64 = base64.b64encode(pcm_16k).decode('utf-8')

                            # 5. Send to ElevenLabs
                            msg = {
                                "user_audio_chunk": out_b64
                            }
                            await self.eleven_ws.send(json.dumps(msg))

                elif event_type == "stop":
                    logger.info("Twilio stream stopped.")
                    break

        except WebSocketDisconnect:
            logger.info("Twilio WebSocket disconnected.")
        except asyncio.CancelledError:
            # Expected during shutdown
            raise
        except Exception as e:
            logger.error(f"Error handling Twilio messages: {e}")
            raise

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
                        # 1. Decode base64
                        chunk = base64.b64decode(payload_b64)

                        # 2. Resample: 16k -> 8k
                        pcm_8k, self.out_rate_state = audioop.ratecv(
                            chunk, 2, 1, 16000, 8000, self.out_rate_state
                        )

                        # 3. Encode: PCM 16-bit 8k -> mulaw 8k
                        ulaw_8k = audioop.lin2ulaw(pcm_8k, 2)

                        # 4. Encode base64
                        out_b64 = base64.b64encode(ulaw_8k).decode('utf-8')

                        # 5. Send to Twilio
                        response = {
                            "event": "media",
                            "streamSid": self.stream_sid,
                            "media": {
                                "payload": out_b64
                            }
                        }
                        await self.twilio_ws.send_text(json.dumps(response))

                elif msg_type == "interruption":
                    if self.stream_sid:
                        await self.twilio_ws.send_text(json.dumps({
                            "event": "clear",
                            "streamSid": self.stream_sid
                        }))

                elif msg_type == "ping":
                    pass

        except asyncio.CancelledError:
            # Expected during shutdown
            raise
        except Exception as e:
            logger.error(f"Error handling ElevenLabs messages: {e}")
            raise

    async def close(self):
        """
        Closes the session cleanly. Idempotent.
        """
        if not self.is_open:
            return

        self.is_open = False

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
        for task in self.tasks:
            if not task.done():
                task.cancel()

        # Wait for tasks to finish cancelling to avoid "Task was destroyed but it is pending!"
        # (Optional but good practice if we want to be super clean, though close() is often fire-and-forget)

        # Explicitly close WebSockets
        if self.eleven_ws:
            try:
                await self.eleven_ws.close()
            except Exception:
                pass # Ignore errors during close

        if self.twilio_ws:
            try:
                # 1000 = Normal Closure
                await self.twilio_ws.close(code=1000)
            except Exception:
                pass # Ignore if already closed
