import logging
import os
from datetime import datetime

LOG_FILE = "admin_audit.log"

# Configure logger
logger = logging.getLogger("admin_audit")
logger.setLevel(logging.INFO)

# File handler
handler = logging.FileHandler(LOG_FILE)
handler.setFormatter(logging.Formatter('%(asctime)s - %(message)s'))
logger.addHandler(handler)

def log_action(admin_username: str, action: str, target: str, details: str = ""):
    """
    Logs an administrative action to the audit log.
    """
    message = f"ADMIN: {admin_username} | ACTION: {action} | TARGET: {target} | DETAILS: {details}"
    logger.info(message)
