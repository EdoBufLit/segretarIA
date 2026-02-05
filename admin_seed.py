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
    admin_username = os.getenv("ADMIN_USERNAME")
    admin_password = os.getenv("ADMIN_PASSWORD")
    admin_email = os.getenv("ADMIN_EMAIL")

    if not admin_username or not admin_password or not admin_email:
        logger.warning(
            "ADMIN_USERNAME, ADMIN_PASSWORD, and ADMIN_EMAIL must be set to seed an admin user. Skipping."
        )
        return

    db = SessionLocal()
    try:
        existing_admin = db.query(User).filter(User.username == admin_username).first()
        if existing_admin:
            if existing_admin.role != "admin":
                logger.info(f"Updating existing admin user '{admin_username}' role from '{existing_admin.role}' to 'admin'.")
                existing_admin.role = "admin"
                db.commit()
            else:
                logger.info(
                    "Default admin user already exists with username '%s' and correct role.",
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
