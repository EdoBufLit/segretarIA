import os
import shutil
import time
import logging
from datetime import datetime, timedelta
from pathlib import Path

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

DB_FILE = "app.db"
BACKUP_DIR = Path("backups")
RETENTION_DAYS = 14

def create_backup():
    if not os.path.exists(DB_FILE):
        logger.error(f"Database file {DB_FILE} not found.")
        return

    BACKUP_DIR.mkdir(exist_ok=True)

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_filename = f"app_backup_{timestamp}.db"
    backup_path = BACKUP_DIR / backup_filename

    try:
        shutil.copy2(DB_FILE, backup_path)
        logger.info(f"Backup created: {backup_path}")
    except Exception as e:
        logger.error(f"Failed to create backup: {e}")

def cleanup_old_backups():
    if not BACKUP_DIR.exists():
        return

    cutoff_time = datetime.now() - timedelta(days=RETENTION_DAYS)

    logger.info(f"Checking for backups older than {RETENTION_DAYS} days (before {cutoff_time})")

    for backup_file in BACKUP_DIR.glob("app_backup_*.db"):
        try:
            # We can use file modification time
            file_mtime = datetime.fromtimestamp(backup_file.stat().st_mtime)

            if file_mtime < cutoff_time:
                backup_file.unlink()
                logger.info(f"Deleted old backup: {backup_file} (Date: {file_mtime})")
            else:
                # logger.debug(f"Keeping backup: {backup_file} (Date: {file_mtime})")
                pass
        except Exception as e:
            logger.error(f"Error processing {backup_file}: {e}")

if __name__ == "__main__":
    create_backup()
    cleanup_old_backups()
