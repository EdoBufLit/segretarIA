import os
from dotenv import load_dotenv
from db import SessionLocal
from models import User, Plan
from auth_utils import hash_password

# Load environment variables from .env file
load_dotenv()

def seed_data():
    """
    Seeds the database with initial data for plans and an admin user.
    This function is idempotent, meaning it can be run multiple times
    without creating duplicate data.
    """
    db = SessionLocal()
    print("Seeding database...")

    try:
        # --- Seed Plans ---
        plans_to_seed = [
            {"code": "basic", "minutes_per_cycle": 300},
            {"code": "pro", "minutes_per_cycle": 1000},
        ]

        for plan_data in plans_to_seed:
            plan = db.query(Plan).filter_by(code=plan_data["code"]).first()
            if not plan:
                new_plan = Plan(
                    code=plan_data["code"],
                    minutes_per_cycle=plan_data["minutes_per_cycle"],
                    is_active=True,
                )
                db.add(new_plan)
                print(f"  - Created plan: {new_plan.code}")
            else:
                print(f"  - Plan '{plan.code}' already exists.")

        # --- Seed Admin User ---
        admin_username = os.getenv("ADMIN_USERNAME", "admin")
        admin_password = os.getenv("ADMIN_PASSWORD")
        admin_email = os.getenv("ADMIN_EMAIL", "admin@example.com")

        if not admin_password:
            raise ValueError("ADMIN_PASSWORD environment variable must be set.")

        admin_user = db.query(User).filter_by(username=admin_username).first()
        if not admin_user:
            hashed_pw = hash_password(admin_password)
            new_admin = User(
                username=admin_username,
                password_hash=hashed_pw,
                email=admin_email,
                role="admin",
                is_active=True,
            )
            db.add(new_admin)
            print(f"  - Created admin user: {new_admin.username}")
        else:
            print(f"  - Admin user '{admin_user.username}' already exists.")

        db.commit()
        print("Seeding complete.")

    except Exception as e:
        print(f"An error occurred during seeding: {e}")
        db.rollback()
    finally:
        db.close()

if __name__ == "__main__":
    seed_data()
