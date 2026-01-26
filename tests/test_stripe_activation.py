import pytest
from unittest.mock import patch, MagicMock
from fastapi.testclient import TestClient
from datetime import datetime, timedelta
from app import app
from db import SessionLocal, Base, engine
from models import User, Subscription, Plan
from auth import hash_password
from admin_seed import ensure_plans

client = TestClient(app)

# Helper to clear DB tables
def clear_db():
    db = SessionLocal()
    try:
        db.query(Subscription).delete()
        db.query(User).filter(User.username.like("stripe_test_%")).delete()
        db.commit()
    finally:
        db.close()

@pytest.fixture(scope="module", autouse=True)
def setup_module():
    Base.metadata.create_all(bind=engine)
    ensure_plans()
    yield
    # Teardown logic if needed

@pytest.fixture
def db_session():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

def test_stripe_checkout_completed_success(db_session):
    # 1. Setup User
    username = "stripe_test_user"
    email = "stripe_test@example.com"

    # Ensure cleanup
    db_session.query(Subscription).delete()
    db_session.query(User).filter(User.email == email).delete()
    db_session.commit()

    user = User(
        username=username,
        email=email,
        password_hash=hash_password("password"),
        role="client",
        is_active=False, # Simulating inactive user
        subscription_plan="NONE"
    )
    db_session.add(user)
    db_session.commit()
    db_session.refresh(user)
    user_id = user.id

    # 2. Mock Payloads
    payload = {
        "id": "evt_test_123",
        "object": "event",
        "type": "checkout.session.completed",
        "data": {
            "object": {
                "client_reference_id": str(user_id),
                "customer": "cus_test_123",
                "subscription": "sub_test_123",
                "metadata": {
                    "plan_code": "pro"
                }
            }
        }
    }

    # 3. Mock External Services
    with patch("stripe_service.stripe.Webhook.construct_event") as mock_construct_event, \
         patch("stripe_service.send_email") as mock_send_email, \
         patch("app.get_queue") as mock_get_queue:

        # Mock Queue to run immediately
        mock_queue = MagicMock()
        def side_effect_enqueue(func, *args, **kwargs):
            func(*args, **kwargs)
        mock_queue.enqueue.side_effect = side_effect_enqueue
        mock_get_queue.return_value = mock_queue

        # Bypass signature verification
        mock_construct_event.return_value = payload

        # 4. Fire Webhook
        # The endpoint expects raw bytes, but TestClient handles json.
        # stripe_service.py: verify_webhook_event takes (payload, sig_header)
        # payload is expected to be bytes. TestClient sending json might be parsed as bytes by Request.body()

        headers = {"stripe-signature": "t=123,v1=signature"}
        response = client.post("/stripe/webhook", json=payload, headers=headers)

        assert response.status_code == 200, f"Response: {response.text}"
        assert response.json() == {"status": "received"}

        # 5. Verify DB Updates
        # Re-fetch user
        db_session.expire_all()
        updated_user = db_session.query(User).filter(User.id == user_id).first()

        # Assert User Fields
        assert updated_user.is_active == True
        assert updated_user.stripe_customer_id == "cus_test_123"
        assert updated_user.subscription_plan == "pro"
        assert updated_user.plan_expires_at is not None
        # Check expiration is roughly 30 days from now
        assert updated_user.plan_expires_at > datetime.utcnow() + timedelta(days=29)

        # Assert Subscription Record
        sub = db_session.query(Subscription).filter(Subscription.user_id == user_id).first()
        assert sub is not None
        assert sub.state == "active"
        assert sub.stripe_subscription_id == "sub_test_123"
        assert sub.plan.code == "pro"
        assert sub.plan.minutes_per_cycle == 180 # Pro minutes

        # 6. Verify Email Sent
        # Expect 2 emails: 1 to Admin (existing), 1 to User (new requirement)
        # We need to check if send_email was called with the user's email

        # Get all calls to send_email
        calls = mock_send_email.call_args_list

        # Check for user email
        user_email_called = False
        for call in calls:
            args, kwargs = call
            if args[0] == email:
                user_email_called = True
                assert "Piano attivato: Pro" in args[1] # Subject check
                # html_body is passed as keyword argument
                html_body = kwargs.get('html_body')
                assert html_body is not None
                assert "180" in html_body # Body check for minutes
                break

        assert user_email_called, "Confirmation email was not sent to the user"

def test_stripe_webhook_invalid_signature():
    with patch("stripe_service.stripe.Webhook.construct_event") as mock_construct:
        mock_construct.side_effect = ValueError("Invalid signature")

        response = client.post("/stripe/webhook", json={}, headers={"stripe-signature": "bad"})
        assert response.status_code == 400
