import sqlite3
import shutil
import os
import glob
from datetime import datetime, timedelta
import logging

# Configuration
DB_FILE = "app.db"
BACKUP_DIR = "backups"
RETENTION_DAYS = 14

# Configure logging (can be integrated with app logger if needed)
logger = logging.getLogger("backup_db")

def perform_backup():
    if not os.path.exists(DB_FILE):
        logger.warning(f"Database file '{DB_FILE}' not found. Skipping backup.")
        return

    if not os.path.exists(BACKUP_DIR):
        os.makedirs(BACKUP_DIR)
        logger.info(f"Created backup directory: {BACKUP_DIR}")

    timestamp = datetime.now().strftime("%Y-%m-%d_%H%M%S")
    backup_filename = f"backup_{timestamp}.db"
    backup_path = os.path.join(BACKUP_DIR, backup_filename)

    try:
        # Use SQLite Online Backup API for safety
        # Connect to source
        conn = sqlite3.connect(DB_FILE)
        # Connect to destination
        bck = sqlite3.connect(backup_path)

        with bck:
            conn.backup(bck)

        bck.close()
        conn.close()

        logger.info(f"Backup created successfully: {backup_path}")
    except Exception as e:
        logger.error(f"Error creating backup: {e}")
        # Fallback to copy if sqlite3 backup fails (e.g. if file is not valid sqlite, though unlikely)
        try:
             shutil.copy2(DB_FILE, backup_path)
             logger.warning(f"Fallback backup (copy) created: {backup_path}")
        except Exception as e2:
             logger.error(f"Fallback backup failed: {e2}")

def enforce_retention():
    if not os.path.exists(BACKUP_DIR):
        return

    cutoff_date = datetime.now() - timedelta(days=RETENTION_DAYS)
    logger.info(f"Checking for backups older than {cutoff_date}...")

    # Pattern match backups
    backup_files = glob.glob(os.path.join(BACKUP_DIR, "backup_*.db"))

    for file_path in backup_files:
        filename = os.path.basename(file_path)
        # Expected format: backup_YYYY-MM-DD_HHMMSS.db
        try:
            # Extract timestamp part
            # backup_ is 7 chars, .db is 3 chars
            timestamp_str = filename[7:-3]
            file_date = datetime.strptime(timestamp_str, "%Y-%m-%d_%H%M%S")

            if file_date < cutoff_date:
                logger.info(f"Deleting old backup: {filename} (Date: {file_date})")
                os.remove(file_path)
            else:
                pass # Keep newer files
        except ValueError:
            logger.warning(f"Skipping unrecognized file format: {filename}")
        except Exception as e:
            logger.error(f"Error processing file {filename}: {e}")

if __name__ == "__main__":
    # Setup basic logging for standalone run
    logging.basicConfig(level=logging.INFO)
    perform_backup()
    enforce_retention()
