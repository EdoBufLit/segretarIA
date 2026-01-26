import pytest
from unittest.mock import patch, MagicMock
from datetime import datetime, timedelta
from fastapi.testclient import TestClient
from app import app
from db import SessionLocal, Base, engine
from models import User, Subscription, Plan
from auth import hash_password
from admin_seed import ensure_plans

client = TestClient(app)

@pytest.fixture(scope="module", autouse=True)
def setup_module():
    Base.metadata.create_all(bind=engine)
    ensure_plans()
    yield

@pytest.fixture
def db_session():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

def test_stripe_invoice_payment_succeeded_updates_expiration(db_session):
    # 1. Setup User & Subscription
    username = "invoice_test_user"
    email = "invoice_test@example.com"

    db_session.query(Subscription).delete()
    db_session.query(User).filter(User.email == email).delete()
    db_session.commit()

    user = User(
        username=username,
        email=email,
        password_hash=hash_password("password"),
        role="client",
        is_active=True,
        subscription_plan="pro",
        stripe_customer_id="cus_invoice_123"
    )
    db_session.add(user)
    db_session.commit()
    db_session.refresh(user)
    user_id = user.id

    plan = db_session.query(Plan).filter(Plan.code == "pro").first()
    sub = Subscription(
        user_id=user_id,
        plan_id=plan.id,
        state="active",
        cycle_start=datetime.utcnow(),
        cycle_end=datetime.utcnow() + timedelta(days=5), # Expiring soon
        stripe_subscription_id="sub_invoice_123"
    )
    db_session.add(sub)
    db_session.commit()

    # 2. Mock Payload (invoice.payment_succeeded)
    # Simulate renewal: period_end is future
    future_ts = int((datetime.utcnow() + timedelta(days=32)).timestamp())

    payload = {
        "id": "evt_invoice_123",
        "object": "event",
        "type": "invoice.payment_succeeded",
        "data": {
            "object": {
                "customer": "cus_invoice_123",
                "subscription": "sub_invoice_123",
                "lines": {
                    "data": [
                        {
                            "period": {
                                "end": future_ts
                            }
                        }
                    ]
                }
            }
        }
    }

    # 3. Fire Webhook
    with patch("stripe_service.stripe.Webhook.construct_event") as mock_construct_event, \
         patch("app.get_queue") as mock_get_queue:

        mock_queue_instance = MagicMock()
        mock_queue_instance.enqueue.side_effect = lambda func, *args, **kwargs: func(*args, **kwargs)
        mock_get_queue.return_value = mock_queue_instance

        mock_construct_event.return_value = payload

        headers = {"stripe-signature": "t=123,v1=signature"}
        response = client.post("/stripe/webhook", json=payload, headers=headers)

        assert response.status_code == 200

        # 4. Verify DB
        db_session.expire_all()
        updated_user = db_session.query(User).filter(User.id == user_id).first()
        updated_sub = db_session.query(Subscription).filter(Subscription.id == sub.id).first()

        # Check sub updated
        assert updated_sub.cycle_end.timestamp() == pytest.approx(future_ts, 1.0)

        # Check USER field synced
        assert updated_user.plan_expires_at is not None
        assert updated_user.plan_expires_at.timestamp() == pytest.approx(future_ts, 1.0)

def test_dashboard_expiration_format(db_session):
    # Setup user with specific expiration date
    username = "dashboard_fmt_user"
    email = "dash_fmt@example.com"

    db_session.query(User).filter(User.email == email).delete()
    db_session.commit()

    # Set expiration: 26 Feb 2026
    expiry = datetime(2026, 2, 26, 12, 0, 0)

    user = User(
        username=username,
        email=email,
        password_hash=hash_password("password"),
        role="client",
        is_active=True,
        subscription_plan="pro", # Essential to trigger "active plan" logic in dashboard
        plan_expires_at=expiry
    )
    db_session.add(user)
    db_session.commit()

    # Login
    client.post("/login", data={"username": username, "password": "password"})

    # Check Dashboard HTML
    response = client.get("/dashboard")
    assert response.status_code == 200

    # Expect "26 febbraio 2026"
    assert "26 febbraio 2026" in response.text
