import logging
import os

from auth import hash_password
from db import SessionLocal
from models import User, Plan

logger = logging.getLogger("app")


def ensure_plans() -> None:
    db = SessionLocal()
    try:
        plans_data = [
            {"code": "starter", "minutes": 60},
            {"code": "pro", "minutes": 180},
            {"code": "business", "minutes": 600},
        ]

        for p in plans_data:
            existing = db.query(Plan).filter(Plan.code == p["code"]).first()
            if not existing:
                new_plan = Plan(code=p["code"], minutes_per_cycle=p["minutes"], is_active=True)
                db.add(new_plan)
                logger.info(f"Created plan '{p['code']}'")
            else:
                # Optional: update if needed, but for now just skip
                pass

        db.commit()
    except Exception as e:
        db.rollback()
        logger.warning(f"Unable to ensure plans: {e}")
    finally:
        db.close()


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
