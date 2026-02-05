import logging
import os
from datetime import datetime
from sqlalchemy.orm import Session
from models import AuditEvent

LOG_FILE = "admin_audit.log"

# Configure logger (legacy file logging)
logger = logging.getLogger("admin_audit")
logger.setLevel(logging.INFO)

# File handler
handler = logging.FileHandler(LOG_FILE)
handler.setFormatter(logging.Formatter('%(asctime)s - %(message)s'))
logger.addHandler(handler)

def log_action(admin_username: str, action: str, target: str, details: str = ""):
    """
    Logs an administrative action to the audit log (File only).
    Legacy support.
    """
    message = f"ADMIN: {admin_username} | ACTION: {action} | TARGET: {target} | DETAILS: {details}"
    logger.info(message)

def log_audit_event(
    db: Session,
    actor_type: str,
    action: str,
    actor_user_id: int = None,
    entity_type: str = None,
    entity_id: str = None,
    meta: dict = None,
    # Legacy params for log_action fallback if needed
    admin_username: str = None,
    target_str: str = None
):
    """
    Logs an audit event to the database and optionally to the file log.
    """
    # Create DB entry
    event = AuditEvent(
        actor_type=actor_type,
        actor_user_id=actor_user_id,
        action=action,
        entity_type=entity_type,
        entity_id=entity_id,
        meta_json=meta
    )
    db.add(event)
    try:
        db.commit()
    except Exception as e:
        db.rollback()
        logger.error(f"Failed to write audit log to DB: {e}")

    # Also log to file if it's an admin action
    if admin_username and target_str:
        log_action(admin_username, action, target_str, str(meta))
    else:
        # Generic log to file
        user_info = f"{actor_type}:{actor_user_id}" if actor_user_id else actor_type
        entity_info = f"{entity_type}:{entity_id}" if entity_type else "N/A"
        message = f"ACTOR: {user_info} | ACTION: {action} | ENTITY: {entity_info} | META: {meta}"
        logger.info(message)
