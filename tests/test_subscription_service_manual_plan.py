import unittest
from datetime import timedelta
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from db import Base
from models import User, Plan, Subscription
from services.subscription_service import ensure_subscription_for_user


class TestSubscriptionServiceManualPlan(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(self.engine)
        self.Session = sessionmaker(bind=self.engine)
        self.db = self.Session()

        plan = Plan(code="pro", minutes_per_cycle=1000)
        self.db.add(plan)
        self.db.commit()
        self.plan = plan

        user = User(
            username="manualuser",
            email="manual@example.com",
            password_hash="hash",
            role="client",
            is_active=True,
            subscription_plan="PRO"
        )
        self.db.add(user)
        self.db.commit()
        self.user = user

    def tearDown(self):
        self.db.close()

    def test_normalizes_plan_and_creates_subscription(self):
        ensure_subscription_for_user(self.db, self.user.id)

        self.db.refresh(self.user)
        subscription = self.db.query(Subscription).filter_by(user_id=self.user.id).first()

        self.assertIsNotNone(subscription)
        self.assertEqual(subscription.plan_id, self.plan.id)
        self.assertEqual(subscription.state, "active")
        self.assertEqual(self.user.subscription_plan, "pro")

        delta = subscription.cycle_end - subscription.cycle_start
        self.assertGreaterEqual(delta, timedelta(days=29))
        self.assertLessEqual(delta, timedelta(days=31))


if __name__ == "__main__":
    unittest.main()
