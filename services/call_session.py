import json
import logging
from typing import Optional
from enum import Enum
from queue_utils import get_redis_connection
from services.timing import log_duration

logger = logging.getLogger("app.services.call_session")

class CallStatus(str, Enum):
    AI_ACTIVE = "ai_active"
    HUMAN_REQUESTED = "human_requested"
    HUMAN_CONNECTED = "human_connected"
    ENDED = "ended"

class CallSessionManager:
    def __init__(self):
        self.redis = get_redis_connection()
        self.ttl = 86400  # 24 hours

    def _key(self, call_sid: str) -> str:
        return f"call_session:{call_sid}"

    def _key_user_active(self, user_id: int) -> str:
        return f"active_call_user:{user_id}"

    def start_session(self, call_sid: str, agent_id: str, phone_number_id: int, status: CallStatus,
                      office_phone_e164: Optional[str] = None, user_id: Optional[int] = None, caller_number: Optional[str] = None):
        key = self._key(call_sid)

        mapping = {
            "status": status.value,
            "agent_id": agent_id,
            "phone_number_id": str(phone_number_id),
            "started_at": str(self.redis.time()[0])
        }
        if office_phone_e164:
            mapping["office_phone_e164"] = office_phone_e164

        if user_id:
            mapping["user_id"] = str(user_id)

        if caller_number:
            mapping["caller_number"] = caller_number

        try:
            with log_duration("redis.hset call_session"):
                self.redis.hset(key, mapping=mapping)

            with log_duration("redis.expire call_session"):
                self.redis.expire(key, self.ttl)

            # Map user to call_sid for dashboard visibility
            if user_id:
                user_key = self._key_user_active(user_id)
                with log_duration("redis.setex active_call_user"):
                    self.redis.setex(user_key, 3600, call_sid) # 1 hour TTL for active mapping

            logger.info(f"Started call session {call_sid} for agent {agent_id} status={status.value}")
        except Exception as e:
            logger.error(f"Failed to start session {call_sid}: {e}")

    def update_status(self, call_sid: str, status: CallStatus):
        key = self._key(call_sid)
        try:
            exists = False
            with log_duration("redis.exists update_status"):
                exists = self.redis.exists(key)

            if exists:
                with log_duration("redis.hset update_status"):
                    self.redis.hset(key, "status", status.value)
                logger.info(f"Updated call session {call_sid} status to {status.value}")
            else:
                logger.warning(f"Attempted to update status for non-existent session {call_sid}")
        except Exception as e:
            logger.error(f"Failed to update status for {call_sid}: {e}")

    def update_stream_sid(self, call_sid: str, stream_sid: str):
        key = self._key(call_sid)
        try:
            exists = False
            with log_duration("redis.exists update_stream_sid"):
                exists = self.redis.exists(key)

            if exists:
                with log_duration("redis.hset update_stream_sid"):
                    self.redis.hset(key, "stream_sid", stream_sid)
                logger.debug(f"Updated stream_sid for {call_sid}")
        except Exception as e:
            logger.error(f"Failed to update stream_sid for {call_sid}: {e}")

    def end_session(self, call_sid: str):
        self.update_status(call_sid, CallStatus.ENDED)
        key = self._key(call_sid)
        try:
            # Clean up user mapping
            session = self.get_session(call_sid)
            if session and "user_id" in session:
                user_key = self._key_user_active(session["user_id"])
                with log_duration("redis.delete active_call_user"):
                    self.redis.delete(user_key)

            with log_duration("redis.expire end_session"):
                self.redis.expire(key, 3600) # Keep for 1 hour after end
        except Exception as e:
            logger.error(f"Failed to set expire for {call_sid}: {e}")

    def get_active_call_for_user(self, user_id: int) -> Optional[dict]:
        """
        Returns the current active session for a user, if any.
        """
        user_key = self._key_user_active(user_id)
        try:
            call_sid_bytes = None
            with log_duration("redis.get active_call_for_user"):
                call_sid_bytes = self.redis.get(user_key)

            if not call_sid_bytes:
                return None
            call_sid = call_sid_bytes.decode()
            session = self.get_session(call_sid)

            # Verify it's actually active
            if session and session.get("status") in [CallStatus.AI_ACTIVE, CallStatus.HUMAN_REQUESTED]:
                session["call_sid"] = call_sid # Attach key
                return session
            return None
        except Exception as e:
            logger.error(f"Failed to get active call for user {user_id}: {e}")
            return None

    def get_session(self, call_sid: str) -> Optional[dict]:
        key = self._key(call_sid)
        try:
            data = None
            with log_duration(f"redis.hgetall session {call_sid}"):
                data = self.redis.hgetall(key)

            if not data:
                return None
            return {k.decode(): v.decode() for k, v in data.items()}
        except Exception as e:
            logger.error(f"Failed to get session {call_sid}: {e}")
            return None
