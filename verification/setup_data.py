from sqlalchemy.orm import Session
from db import SessionLocal
from models import User, Subscription, Plan
from auth import hash_password
from datetime import datetime, timedelta

def setup_data():
    db = SessionLocal()

    # Plans
    plan = db.query(Plan).filter(Plan.code == "pro").first()
    if not plan:
        plan = Plan(code="pro", minutes_per_cycle=100, is_active=True)
        db.add(plan)
        db.commit()

    # 1. Suspended Client (No Active Plan)
    client_suspended = db.query(User).filter(User.username == "client_suspended").first()
    if not client_suspended:
        client_suspended = User(
            username="client_suspended",
            email="client_suspended@example.com",
            password_hash=hash_password("password"),
            role="client",
            is_active=True,
            studio_name="Studio Suspended"
        )
        db.add(client_suspended)
        db.commit()

    # Ensure Canceled subscription
    sub = db.query(Subscription).filter(Subscription.user_id == client_suspended.id).first()
    if not sub:
        sub = Subscription(
            user_id=client_suspended.id,
            plan_id=plan.id,
            state="canceled",
            cycle_start=datetime.utcnow(),
            cycle_end=datetime.utcnow() + timedelta(days=30)
        )
        db.add(sub)
    else:
        sub.state = "canceled"
    db.commit()

    # 2. Active Client (Active Plan)
    client_active = db.query(User).filter(User.username == "client_active").first()
    if not client_active:
        client_active = User(
            username="client_active",
            email="client_active@example.com",
            password_hash=hash_password("password"),
            role="client",
            is_active=True,
            studio_name="Studio Active"
        )
        db.add(client_active)
        db.commit()

    # Ensure Active subscription
    sub_active = db.query(Subscription).filter(Subscription.user_id == client_active.id).first()
    if not sub_active:
        sub_active = Subscription(
            user_id=client_active.id,
            plan_id=plan.id,
            state="active",
            cycle_start=datetime.utcnow(),
            cycle_end=datetime.utcnow() + timedelta(days=30)
        )
        db.add(sub_active)
    else:
        sub_active.state = "active"
    db.commit()

    print("Data setup complete.")

if __name__ == "__main__":
    setup_data()
