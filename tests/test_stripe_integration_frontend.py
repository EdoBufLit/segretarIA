import sys
import os
import unittest
from unittest.mock import patch, MagicMock
from fastapi.testclient import TestClient
from datetime import datetime, timedelta
import logging

# Append root to sys.path
sys.path.append(os.getcwd())

# Set required environment variables BEFORE importing app
os.environ["SECRET_KEY"] = "super_secret_key_for_testing_1234567890"
os.environ["STRIPE_SECRET_KEY"] = "sk_test_mock_12345"
os.environ["STRIPE_PUBLIC_KEY"] = "pk_test_mock_12345"
os.environ["ADMIN_EMAIL"] = "admin@example.com"

from app import app
from db import SessionLocal, Base, engine
from models import User, Subscription, Plan
from auth import hash_password
from admin_seed import ensure_plans

# Disable logging for cleaner output during test
logging.getLogger("app").setLevel(logging.CRITICAL)
logging.getLogger("stripe_service").setLevel(logging.CRITICAL)

class TestStripeFrontendIntegration(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        Base.metadata.create_all(bind=engine)
        ensure_plans()
        cls.client = TestClient(app)
        cls.db = SessionLocal()

    @classmethod
    def tearDownClass(cls):
        cls.db.close()

    def setUp(self):
        # Cleanup
        self.db.query(Subscription).delete()
        self.db.query(User).filter(User.username.like("check_test_%")).delete()
        self.db.commit()

        # Create Client User
        self.client_user = User(
            username="check_test_user",
            email="check_test@example.com",
            password_hash=hash_password("password123"),
            role="client",
            is_active=False,
            subscription_plan="NONE"
        )
        self.db.add(self.client_user)

        # Create Admin User
        self.admin_user = User(
            username="check_test_admin",
            email="admin_test@example.com",
            password_hash=hash_password("password123"),
            role="admin",
            is_active=True
        )
        self.db.add(self.admin_user)
        self.db.commit()
        self.db.refresh(self.client_user)
        self.db.refresh(self.admin_user)

    def test_full_checkout_flow(self):
        print("\n--- Starting Stripe Full Checkout Verification ---")

        # 1. Simulate Stripe Webhook (Checkout Completed -> Starter Plan)
        payload = {
            "id": "evt_test_checkout",
            "object": "event",
            "type": "checkout.session.completed",
            "data": {
                "object": {
                    "client_reference_id": str(self.client_user.id),
                    "customer": "cus_sandbox_123",
                    "subscription": "sub_sandbox_123",
                    "metadata": {
                        "plan_code": "starter"
                    }
                }
            }
        }

        with patch("stripe_service.stripe.Webhook.construct_event") as mock_construct, \
             patch("stripe_service.send_email") as mock_email, \
             patch("app.get_queue") as mock_get_queue:

            # Setup Mocks
            mock_construct.return_value = payload
            mock_queue = MagicMock()
            mock_queue.enqueue.side_effect = lambda func, *args, **kwargs: func(*args, **kwargs)
            mock_get_queue.return_value = mock_queue

            # Send Webhook
            print("[Step 1] Sending Webhook...")
            response = self.client.post("/stripe/webhook", json=payload, headers={"stripe-signature": "dummy"})
            self.assertEqual(response.status_code, 200)
            print(" -> Webhook processed successfully.")

        # 2. Verify Backend State
        print("[Step 2] Verifying Backend State...")
        self.db.expire_all()
        user = self.db.query(User).filter(User.id == self.client_user.id).first()
        sub = self.db.query(Subscription).filter(Subscription.user_id == user.id).first()

        self.assertEqual(user.subscription_plan, "starter")
        self.assertTrue(user.is_active)
        self.assertIsNotNone(user.plan_expires_at)

        # Verify expiration is approx 30 days
        days_diff = (user.plan_expires_at - datetime.utcnow()).days
        self.assertTrue(28 <= days_diff <= 31, f"Expiration days {days_diff} not in expected range")

        self.assertIsNotNone(sub)
        self.assertEqual(sub.state, "active")
        print(f" -> Backend Verified: Plan={user.subscription_plan}, Active={user.is_active}, Expires={user.plan_expires_at}")

        # 3. Frontend Verification (User Dashboard)
        print("[Step 3] Verifying User Dashboard HTML...")

        # Login
        # TestClient follows redirects by default, so this will end up at /dashboard (200 OK)
        login_resp = self.client.post("/login", data={"username": "check_test_user", "password": "password123"})
        self.assertEqual(login_resp.status_code, 200)

        # Verify we are on the dashboard
        html = login_resp.text

        # Checks
        # Badge
        self.assertIn("STARTER", html.upper()) # Badge text usually uppercase in HTML or rendered as such

        # Minutes (Starter = 60)
        self.assertIn("60", html)

        # Expiration Date Format
        months_it = {
            1: "gennaio", 2: "febbraio", 3: "marzo", 4: "aprile", 5: "maggio", 6: "giugno",
            7: "luglio", 8: "agosto", 9: "settembre", 10: "ottobre", 11: "novembre", 12: "dicembre"
        }
        exp_date = user.plan_expires_at
        exp_str = f"{exp_date.day} {months_it[exp_date.month]} {exp_date.year}"

        print(f" -> Expecting date string: '{exp_str}'")
        self.assertIn(exp_str, html)
        print(" -> User Dashboard Verified.")

        # 4. Frontend Verification (Admin Dashboard / API)
        print("[Step 4] Verifying Admin API...")

        # Login Admin
        self.client.cookies.clear() # Clear user session
        admin_login = self.client.post("/login", data={"username": "check_test_admin", "password": "password123"})
        self.assertEqual(admin_login.status_code, 200)

        # GET Users API
        users_resp = self.client.get("/admin/users")
        self.assertEqual(users_resp.status_code, 200)
        users_data = users_resp.json()

        # Find our user
        target_item = None
        for item in users_data["items"]:
            if item["id"] == user.id:
                target_item = item
                break

        self.assertIsNotNone(target_item)
        self.assertEqual(target_item["subscription_plan"], "starter")

        # API returns YYYY-MM-DD
        api_date_str = target_item["plan_expires_at"]
        expected_api_date = user.plan_expires_at.strftime("%Y-%m-%d")
        self.assertEqual(api_date_str, expected_api_date)

        print(f" -> Admin API Verified: Plan={target_item['subscription_plan']}, Date={api_date_str}")
        print("\n--- SUCCESS: All Checks Passed ---")

if __name__ == "__main__":
    unittest.main()
