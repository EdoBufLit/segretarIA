import unittest
from unittest.mock import MagicMock, patch
from sqlalchemy.orm import Session
from stripe_service import StripeService
from models import User, Subscription, Plan, AuditEvent
import os

class TestStripeServiceNotifications(unittest.TestCase):
    def setUp(self):
        self.db = MagicMock(spec=Session)
        self.service = StripeService(self.db)
        # Mock environment
        self.env_patcher = patch.dict(os.environ, {"ADMIN_BILLING_EMAIL": "admin@test.com", "STRIPE_SECRET_KEY": "mock"})
        self.env_patcher.start()

    def tearDown(self):
        self.env_patcher.stop()

    @patch("stripe_service.send_email")
    def test_notify_admin_payment_success_sends_email_if_not_exists(self, mock_send_email):
        # Setup
        user = User(id=1, username="testuser", email="test@test.com", studio_name="Test Studio")
        plan_code = "pro"
        transaction_id = "checkout:cs_123"

        # Mock DB query for AuditEvent (return None -> not exists)
        self.db.query.return_value.filter_by.return_value.first.return_value = None

        # Execute
        self.service._notify_admin_payment_success(user, plan_code, transaction_id, "Test Context")

        # Verify
        mock_send_email.assert_called_once()
        args = mock_send_email.call_args[0]
        self.assertEqual(args[0], "admin@test.com")
        self.assertIn("[PAYMENT]", args[1])

        # Verify DB add for AuditEvent
        self.db.add.assert_called_once()
        added_event = self.db.add.call_args[0][0]
        self.assertIsInstance(added_event, AuditEvent)
        self.assertEqual(added_event.action, "admin_notification_payment_success")
        self.assertEqual(added_event.entity_id, transaction_id)

    @patch("stripe_service.send_email")
    def test_notify_admin_payment_success_skips_if_exists(self, mock_send_email):
        # Setup
        user = User(id=1, username="testuser", email="test@test.com")
        plan_code = "pro"
        transaction_id = "checkout:cs_123"

        # Mock DB query for AuditEvent (return existing event)
        self.db.query.return_value.filter_by.return_value.first.return_value = AuditEvent(id=1)

        # Execute
        self.service._notify_admin_payment_success(user, plan_code, transaction_id, "Test Context")

        # Verify
        mock_send_email.assert_not_called()
        self.db.add.assert_not_called()

if __name__ == '__main__':
    unittest.main()
