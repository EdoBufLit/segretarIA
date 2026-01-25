import os
import json
import httpx
import logging
from datetime import datetime
from queue_utils import get_redis_connection

logger = logging.getLogger("alerting")

# Redis Keys
KEY_LAST_WEBHOOK_TIME = "last_webhook_time"
KEY_LAST_WEBHOOK_INFO = "last_webhook_info"
KEY_LAST_EMAIL_TIME = "last_email_time"
KEY_LAST_EMAIL_TO = "last_email_to"
KEY_CRITICAL_ERRORS = "critical_errors"

def send_telegram_alert(message: str, parse_mode: str = None):
    """
    Sends a message to the configured Telegram chat.
    Uses sync HTTP client to be safe in exception handlers.
    """
    bot_token = os.getenv("TELEGRAM_BOT_TOKEN")
    chat_id = os.getenv("TELEGRAM_ADMIN_CHAT_ID")

    if not bot_token or not chat_id:
        # Config missing, just log it
        logger.debug("Telegram alert skipped (config missing)")
        return

    url = f"https://api.telegram.org/bot{bot_token}/sendMessage"

    payload = {"chat_id": chat_id, "text": message}
    if parse_mode:
        payload["parse_mode"] = parse_mode

    try:
        with httpx.Client(timeout=5.0) as client:
            resp = client.post(url, data=payload)
            if resp.status_code != 200:
                logger.error(f"[Telegram] Failed to send alert: {resp.text}")
    except Exception as e:
        logger.error(f"[Telegram] Error sending alert: {e}")

def log_critical_error(message: str, context: dict = None):
    """
    Logs a critical error to Redis and sends a Telegram alert.
    Tries to send Telegram alert even if Redis fails.
    """
    # 1. Send Telegram Alert (Priority)
    try:
        alert_msg = f"⚠️ CRITICAL ERROR\n{message}"
        if context:
            alert_msg += "\n\nContext:\n" + "\n".join([f"- {k}: {v}" for k, v in context.items()])
        send_telegram_alert(alert_msg)
    except Exception as e:
        logger.error(f"Failed to send Telegram alert: {e}")

    # 2. Log to Redis
    try:
        redis = get_redis_connection()
        timestamp = datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")

        # Format for Redis
        error_entry = f"[{timestamp}] {message}"
        if context:
            context_str = " | ".join([f"{k}={v}" for k, v in context.items()])
            error_entry += f" ({context_str})"

        # Push to Redis (keep last 50)
        redis.lpush(KEY_CRITICAL_ERRORS, error_entry)
        redis.ltrim(KEY_CRITICAL_ERRORS, 0, 49)
    except Exception as e:
        logger.error(f"Failed to log critical error to Redis: {e}")

def notify_chat_message(user, message_content: str):
    """
    Sends a Telegram alert for a new client chat message.
    """
    try:
        # Truncate message
        preview = message_content[:250] + ("..." if len(message_content) > 250 else "")

        # Build public URL for admin (heuristic)
        base_url = os.getenv("DOMAIN_NAME", "http://localhost:8000")
        if not base_url.startswith("http"):
            base_url = f"https://{base_url}"

        chat_url = f"{base_url.rstrip('/')}/dashboard#section-chat" # Admin dashboard anchor

        identifier = user.studio_name or user.username or user.email

        msg = (
            f"💬 <b>Nuovo messaggio dal cliente {identifier}</b>\n\n"
            f"<i>{preview}</i>\n\n"
            f"<a href='{chat_url}'>Apri Chat Admin</a>"
        )

        send_telegram_alert(msg, parse_mode="HTML")
    except Exception as e:
        logger.error(f"Failed to send chat notification: {e}")

def track_webhook_success(agent_id: str, call_id: str):
    """
    Updates the last webhook received timestamp and info in Redis.
    """
    try:
        redis = get_redis_connection()
        now = datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")

        redis.set(KEY_LAST_WEBHOOK_TIME, now)
        redis.set(KEY_LAST_WEBHOOK_INFO, json.dumps({"agent_id": agent_id, "call_id": call_id}))
    except Exception as e:
        logger.error(f"Failed to track webhook success: {e}")

def track_email_success(recipient: str):
    """
    Updates the last email sent timestamp and info in Redis.
    """
    try:
        redis = get_redis_connection()
        now = datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")

        redis.set(KEY_LAST_EMAIL_TIME, now)
        redis.set(KEY_LAST_EMAIL_TO, recipient)
    except Exception as e:
        logger.error(f"Failed to track email success: {e}")

def get_monitoring_stats():
    """
    Retrieves monitoring stats from Redis.
    Returns:
        dict: {
            "last_webhook_time": str|None,
            "last_webhook_info": dict|None,
            "last_email_time": str|None,
            "last_email_to": str|None,
            "recent_errors": list[str]
        }
    """
    stats = {
        "last_webhook_time": None,
        "last_webhook_info": None,
        "last_email_time": None,
        "last_email_to": None,
        "recent_errors": []
    }

    try:
        redis = get_redis_connection()

        # Webhook
        stats["last_webhook_time"] = redis.get(KEY_LAST_WEBHOOK_TIME)
        if stats["last_webhook_time"]:
            stats["last_webhook_time"] = stats["last_webhook_time"].decode('utf-8')

        webhook_info = redis.get(KEY_LAST_WEBHOOK_INFO)
        if webhook_info:
            stats["last_webhook_info"] = json.loads(webhook_info)

        # Email
        stats["last_email_time"] = redis.get(KEY_LAST_EMAIL_TIME)
        if stats["last_email_time"]:
            stats["last_email_time"] = stats["last_email_time"].decode('utf-8')

        stats["last_email_to"] = redis.get(KEY_LAST_EMAIL_TO)
        if stats["last_email_to"]:
            stats["last_email_to"] = stats["last_email_to"].decode('utf-8')

        # Errors (limit 5 for display, but list has 50)
        errors = redis.lrange(KEY_CRITICAL_ERRORS, 0, 4)
        if errors:
            stats["recent_errors"] = [e.decode('utf-8') for e in errors]

    except Exception as e:
        logger.error(f"Failed to get monitoring stats: {e}")

    return stats
