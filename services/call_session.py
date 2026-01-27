import json
import logging
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

    def start_session(self, call_sid: str, agent_id: str, phone_number_id: int, status: CallStatus, office_phone_e164: Optional[str] = None):
        key = self._key(call_sid)

        mapping = {
            "status": status.value,
            "agent_id": agent_id,
            "phone_number_id": str(phone_number_id),
            "started_at": str(self.redis.time()[0])
        }
        if office_phone_e164:
            mapping["office_phone_e164"] = office_phone_e164

        try:
            self.redis.hset(key, mapping=mapping)
            self.redis.expire(key, self.ttl)
            logger.info(f"Started call session {call_sid} for agent {agent_id} status={status.value}")
        except Exception as e:
            logger.error(f"Failed to start session {call_sid}: {e}")

    def update_status(self, call_sid: str, status: CallStatus):
        key = self._key(call_sid)
        try:
            if self.redis.exists(key):
                self.redis.hset(key, "status", status.value)
                logger.info(f"Updated call session {call_sid} status to {status.value}")
            else:
                logger.warning(f"Attempted to update status for non-existent session {call_sid}")
        except Exception as e:
            logger.error(f"Failed to update status for {call_sid}: {e}")

    def update_stream_sid(self, call_sid: str, stream_sid: str):
        key = self._key(call_sid)
        try:
            if self.redis.exists(key):
                self.redis.hset(key, "stream_sid", stream_sid)
                logger.debug(f"Updated stream_sid for {call_sid}")
        except Exception as e:
            logger.error(f"Failed to update stream_sid for {call_sid}: {e}")

    def end_session(self, call_sid: str):
        self.update_status(call_sid, CallStatus.ENDED)
        key = self._key(call_sid)
        try:
            self.redis.expire(key, 3600) # Keep for 1 hour after end
        except Exception as e:
            logger.error(f"Failed to set expire for {call_sid}: {e}")

    def get_session(self, call_sid: str) -> Optional[dict]:
        key = self._key(call_sid)
        try:
            data = self.redis.hgetall(key)
            if not data:
                return None
            return {k.decode(): v.decode() for k, v in data.items()}
        except Exception as e:
            logger.error(f"Failed to get session {call_sid}: {e}")
            return None
