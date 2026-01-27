import json
import logging
import time
from typing import Optional
from enum import Enum
from queue_utils import get_redis_connection

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
            hset_start = time.perf_counter()
            self.redis.hset(key, mapping=mapping)
            self._log_duration("redis.hset call_session", hset_start)

            expire_start = time.perf_counter()
            self.redis.expire(key, self.ttl)
            self._log_duration("redis.expire call_session", expire_start)

            # Map user to call_sid for dashboard visibility
            if user_id:
                user_key = self._key_user_active(user_id)
                setex_start = time.perf_counter()
                self.redis.setex(user_key, 3600, call_sid) # 1 hour TTL for active mapping
                self._log_duration("redis.setex active_call_user", setex_start)

            logger.info(f"Started call session {call_sid} for agent {agent_id} status={status.value}")
        except Exception as e:
            logger.error(f"Failed to start session {call_sid}: {e}")

    def update_status(self, call_sid: str, status: CallStatus):
        key = self._key(call_sid)
        try:
            exists_start = time.perf_counter()
            exists = self.redis.exists(key)
            self._log_duration("redis.exists call_session", exists_start)
            if exists:
                hset_start = time.perf_counter()
                self.redis.hset(key, "status", status.value)
                self._log_duration("redis.hset status", hset_start)
                logger.info(f"Updated call session {call_sid} status to {status.value}")
            else:
                logger.warning(f"Attempted to update status for non-existent session {call_sid}")
        except Exception as e:
            logger.error(f"Failed to update status for {call_sid}: {e}")

    def update_stream_sid(self, call_sid: str, stream_sid: str):
        key = self._key(call_sid)
        try:
            exists_start = time.perf_counter()
            exists = self.redis.exists(key)
            self._log_duration("redis.exists call_session", exists_start)
            if exists:
                hset_start = time.perf_counter()
                self.redis.hset(key, "stream_sid", stream_sid)
                self._log_duration("redis.hset stream_sid", hset_start)
                logger.debug(f"Updated stream_sid for {call_sid}")
        except Exception as e:
            logger.error(f"Failed to update stream_sid for {call_sid}: {e}")

    def end_session(self, call_sid: str):
        self.update_status(call_sid, CallStatus.ENDED)
        key = self._key(call_sid)
        try:
            # Clean up user mapping
            session_start = time.perf_counter()
            session = self.get_session(call_sid)
            self._log_duration("redis.hgetall call_session", session_start)
            if session and "user_id" in session:
                user_key = self._key_user_active(session["user_id"])
                delete_start = time.perf_counter()
                self.redis.delete(user_key)
                self._log_duration("redis.delete active_call_user", delete_start)

            expire_start = time.perf_counter()
            self.redis.expire(key, 3600) # Keep for 1 hour after end
            self._log_duration("redis.expire call_session", expire_start)
        except Exception as e:
            logger.error(f"Failed to set expire for {call_sid}: {e}")

    def get_active_call_for_user(self, user_id: int) -> Optional[dict]:
        """
        Returns the current active session for a user, if any.
        """
        user_key = self._key_user_active(user_id)
        try:
            get_start = time.perf_counter()
            call_sid_bytes = self.redis.get(user_key)
            self._log_duration("redis.get active_call_user", get_start)
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
            hgetall_start = time.perf_counter()
            data = self.redis.hgetall(key)
            self._log_duration("redis.hgetall call_session", hgetall_start)
            if not data:
                return None
            return {k.decode(): v.decode() for k, v in data.items()}
        except Exception as e:
            logger.error(f"Failed to get session {call_sid}: {e}")
            return None

    def _log_duration(self, label: str, start_time: float):
        duration_ms = (time.perf_counter() - start_time) * 1000
        lag = " (LAG!)" if duration_ms > 500 else ""
        logger.info(f"{label} | duration: {duration_ms:.0f}ms{lag}")
