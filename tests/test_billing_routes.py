import os
from datetime import datetime, timedelta
from unittest.mock import patch

from fastapi.testclient import TestClient
from app import app
from db import SessionLocal, Base, engine
from models import User, Subscription, Plan
from auth import hash_password
from admin_seed import ensure_plans

client = TestClient(app)

def setup_module(module):
    Base.metadata.create_all(bind=engine)
    ensure_plans()
    db = SessionLocal()
    if not db.query(User).filter_by(username="testclient").first():
        user = User(
            username="testclient",
            email="testclient@example.com",
            password_hash=hash_password("password"),
            role="client",
            is_active=True
        )
        db.add(user)
        db.commit()
    db.close()

def test_plans_page_accessible_unauthenticated():
    response = client.get("/billing/plans")
    assert response.status_code == 200
    assert "Starter" in response.text
    assert "Pro" in response.text
    assert "Business" in response.text

def test_plans_page_accessible_authenticated():
    # Login first
    client.post("/login", data={"username": "testclient", "password": "password"})
    response = client.get("/billing/plans")
    assert response.status_code == 200
    assert "Starter" in response.text

def test_cancel_subscription_schedules_cancellation():
    db = SessionLocal()
    user = db.query(User).filter_by(username="testclient").first()
    plan = db.query(Plan).filter_by(code="starter").first()
    assert user is not None
    assert plan is not None

    db.query(Subscription).filter(Subscription.user_id == user.id).delete()
    db.commit()

    cycle_start = datetime.utcnow() - timedelta(days=2)
    cycle_end = datetime.utcnow() + timedelta(days=28)
    sub = Subscription(
        user_id=user.id,
        plan_id=plan.id,
        state="active",
        cycle_start=cycle_start,
        cycle_end=cycle_end,
        stripe_subscription_id="sub_cancel_test",
        stripe_price_id="price_test"
    )
    db.add(sub)
    db.commit()
    db.close()

    os.environ["STRIPE_SECRET_KEY"] = "sk_test_mock"

    client.post("/login", data={"username": "testclient", "password": "password"})

    with patch("stripe_service.stripe.Subscription.modify") as mock_modify:
        mock_modify.return_value = {
            "cancel_at_period_end": True,
            "current_period_end": int(cycle_end.timestamp())
        }
        response = client.post("/api/billing/subscription/cancel")

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "ok"
    assert payload["cancel_at_period_end"] is True

    db = SessionLocal()
    sub = db.query(Subscription).filter_by(user_id=user.id, stripe_subscription_id="sub_cancel_test").first()
    assert sub is not None
    assert sub.cancel_requested_at is not None
    assert sub.state == "active"
    db.close()
