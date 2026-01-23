import logging
import os

from auth import hash_password
from db import SessionLocal
from models import User

logger = logging.getLogger("app")


def ensure_default_admin() -> None:
    admin_username = os.getenv("ADMIN_USERNAME", "admin")
    admin_password = os.getenv("ADMIN_PASSWORD", "password123")
    admin_email = os.getenv("ADMIN_EMAIL", "admin@example.com")

    db = SessionLocal()
    try:
        existing_admin = db.query(User).filter(User.username == admin_username).first()
        if existing_admin:
            logger.info(
                "Default admin user already exists with username '%s'.",
                admin_username,
            )
            return

        admin_user = User(
            username=admin_username,
            email=admin_email,
            password_hash=hash_password(admin_password),
            role="admin",
            is_active=True,
        )
        db.add(admin_user)
        db.commit()
        logger.info(
            "Default admin user created with username '%s'.",
            admin_username,
        )
    except Exception as exc:
        db.rollback()
        logger.warning("Unable to ensure default admin user: %s", exc)
    finally:
        db.close()
