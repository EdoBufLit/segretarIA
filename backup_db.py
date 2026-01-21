import shutil
import os
from datetime import datetime

DB_FILE = "app.db"
BACKUP_DIR = "backups"

def backup_database():
    if not os.path.exists(DB_FILE):
        print(f"Error: Database file '{DB_FILE}' not found.")
        return

    if not os.path.exists(BACKUP_DIR):
        os.makedirs(BACKUP_DIR)
        print(f"Created backup directory: {BACKUP_DIR}")

    timestamp = datetime.now().strftime("%Y-%m-%d")
    backup_filename = f"backup_{timestamp}.db"
    destination = os.path.join(BACKUP_DIR, backup_filename)

    try:
        shutil.copy2(DB_FILE, destination)
        print(f"Database backup created successfully: {destination}")
    except Exception as e:
        print(f"Error copying database file: {e}")

if __name__ == "__main__":
    backup_database()
