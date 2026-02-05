import sys
import os
import logging

# Append root directory to sys.path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from db import SessionLocal
from models import User
from services.subscription_service import ensure_subscription_for_user

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("backfill")

def main():
    logger.info("Starting subscription backfill...")
    db = SessionLocal()
    try:
        users = db.query(User).all()
        logger.info(f"Found {len(users)} users.")

        for user in users:
            try:
                logger.info(f"Processing user {user.id} ({user.username})...")
                ensure_subscription_for_user(db, user.id)
            except Exception as e:
                logger.error(f"Error processing user {user.id}: {e}")

        logger.info("Backfill completed.")
    finally:
        db.close()

if __name__ == "__main__":
    main()
