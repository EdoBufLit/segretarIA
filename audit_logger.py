from datetime import datetime
import os

AUDIT_LOG_FILE = "admin_audit.log"

def log_admin_action(username: str, action: str):
    timestamp = datetime.utcnow().isoformat()
    entry = f"{timestamp} | Admin: {username} | Action: {action}\n"

    with open(AUDIT_LOG_FILE, "a") as f:
        f.write(entry)
