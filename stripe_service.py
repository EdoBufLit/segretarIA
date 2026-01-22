import stripe
import os
from datetime import datetime, timedelta
from sqlalchemy.orm import Session
from models import User, Subscription, Plan
import logging

logger = logging.getLogger("stripe_service")

class StripeService:
    def __init__(self, db: Session):
        self.db = db
        self.api_key = os.getenv("STRIPE_SECRET_KEY")
        self.webhook_secret = os.getenv("STRIPE_WEBHOOK_SECRET")
        if self.api_key:
            stripe.api_key = self.api_key
        else:
            logger.warning("STRIPE_SECRET_KEY not set")

    def create_checkout_session(self, user_id: int, plan_code: str, success_url: str, cancel_url: str):
        # MOCK FOR QA
        if self.api_key == "mock":
            class MockSession:
                url = "http://mock-checkout-url.com"
            return MockSession()

        if not self.api_key:
            raise ValueError("Stripe not configured")

        user = self.db.query(User).filter(User.id == user_id).first()
        if not user:
            raise ValueError("User not found")

        # Map plan_code to Stripe Price ID
        # In a real app, this might be in DB or config.
        # For now, we mock or use env vars.
        price_id = os.getenv(f"STRIPE_PRICE_ID_{plan_code.upper()}")
        if not price_id:
            # Fallback for testing if not in env
            price_id = "price_mock_123"

        try:
            checkout_session = stripe.checkout.Session.create(
                payment_method_types=['card'],
                line_items=[
                    {
                        'price': price_id,
                        'quantity': 1,
                    },
                ],
                mode='subscription',
                success_url=success_url,
                cancel_url=cancel_url,
                client_reference_id=str(user.id),
                customer_email=user.email,
                metadata={
                    "plan_code": plan_code
                }
            )
            return checkout_session
        except Exception as e:
            logger.error(f"Stripe Checkout Error: {e}")
            raise

    def handle_webhook_event(self, payload: bytes, sig_header: str):
        # MOCK FOR QA
        if self.webhook_secret == "mock":
             import json
             event = json.loads(payload)
        else:
            if not self.webhook_secret:
                 pass

            try:
                event = stripe.Webhook.construct_event(
                    payload, sig_header, self.webhook_secret
                )
            except ValueError as e:
                # Invalid payload
                raise ValueError("Invalid payload")
            except stripe.error.SignatureVerificationError as e:
                # Invalid signature
                raise ValueError("Invalid signature")

        event_type = event['type']
        data = event['data']['object']

        if event_type == 'checkout.session.completed':
            self._handle_checkout_completed(data)
        elif event_type == 'invoice.payment_succeeded':
            self._handle_payment_succeeded(data)
        elif event_type == 'invoice.payment_failed':
            self._handle_payment_failed(data)
        elif event_type == 'customer.subscription.deleted':
            self._handle_subscription_deleted(data)

        return {"status": "success"}

    def _handle_checkout_completed(self, session):
        # Activate subscription
        user_id_str = session.get('client_reference_id')
        if not user_id_str:
            logger.error("No client_reference_id in session")
            return

        user_id = int(user_id_str)
        stripe_customer_id = session.get('customer')
        stripe_subscription_id = session.get('subscription')

        # metadata should have plan_code
        plan_code = session.get('metadata', {}).get('plan_code', 'pro')

        logger.info(f"Processing checkout success for user {user_id}, plan {plan_code}")

        user = self.db.query(User).filter(User.id == user_id).first()
        if not user:
            logger.error(f"User {user_id} not found")
            return

        # Update User
        user.stripe_customer_id = stripe_customer_id
        # Reactivate if suspended? Yes.
        user.is_active = True

        # Update/Create Subscription
        plan = self.db.query(Plan).filter(Plan.code == plan_code).first()
        if not plan:
            logger.error(f"Plan {plan_code} not found")
            # Fallback?
            return

        subscription = self.db.query(Subscription).filter_by(user_id=user_id).first()
        if not subscription:
            subscription = Subscription(
                user_id=user_id,
                plan_id=plan.id,
                state="active",
                cycle_start=datetime.utcnow(),
                cycle_end=datetime.utcnow() + timedelta(days=30),
                stripe_subscription_id=stripe_subscription_id,
                stripe_price_id=None # We might get this from items in webhook if we parse deeply, skipping for now
            )
            self.db.add(subscription)
        else:
            subscription.plan_id = plan.id
            subscription.state = "active"
            subscription.cycle_start = datetime.utcnow()
            subscription.cycle_end = datetime.utcnow() + timedelta(days=30)
            subscription.stripe_subscription_id = stripe_subscription_id
            # subscription.stripe_price_id = ...

        self.db.commit()

    def _handle_payment_failed(self, invoice):
        stripe_customer_id = invoice.get('customer')
        if not stripe_customer_id:
            logger.error("No customer ID in invoice")
            return

        user = self.db.query(User).filter_by(stripe_customer_id=stripe_customer_id).first()
        if not user:
            logger.error(f"User with stripe_customer_id {stripe_customer_id} not found")
            return

        logger.info(f"Processing payment failure for user {user.id}")

        # Suspend User
        user.is_active = False

        # Mark subscription past_due
        # We need to find the subscription by stripe_subscription_id ideally, or just the active one for the user
        subscription_id = invoice.get('subscription')
        if subscription_id:
            sub = self.db.query(Subscription).filter_by(stripe_subscription_id=subscription_id).first()
            if sub:
                sub.state = "past_due"
        else:
            # Fallback: update user's active subscription
            sub = self.db.query(Subscription).filter_by(user_id=user.id, state="active").first()
            if sub:
                sub.state = "past_due"

        self.db.commit()

    def _handle_payment_succeeded(self, invoice):
        stripe_customer_id = invoice.get('customer')
        if not stripe_customer_id:
            return

        user = self.db.query(User).filter_by(stripe_customer_id=stripe_customer_id).first()
        if not user:
            return

        logger.info(f"Processing payment success for user {user.id}. Restoring service.")

        # Restore User
        user.is_active = True

        # Restore Subscription
        subscription_id = invoice.get('subscription')
        if subscription_id:
            sub = self.db.query(Subscription).filter_by(stripe_subscription_id=subscription_id).first()
            if sub:
                sub.state = "active"
                # Update cycle_end if period_end is present
                lines = invoice.get('lines', {}).get('data', [])
                if lines:
                    period_end = lines[0].get('period', {}).get('end')
                    if period_end:
                        sub.cycle_end = datetime.fromtimestamp(period_end)
        else:
            # Fallback: find past_due subscription
            sub = self.db.query(Subscription).filter_by(user_id=user.id, state="past_due").first()
            if sub:
                sub.state = "active"
                # Extend simply by 30 days if no period data? Or leave as is if only restoring access.
                # Assuming simple restoration logic.
                sub.cycle_end = datetime.utcnow() + timedelta(days=30)

        self.db.commit()

    def _handle_subscription_deleted(self, subscription):
        stripe_customer_id = subscription.get('customer')
        stripe_subscription_id = subscription.get('id')

        if not stripe_customer_id:
            return

        user = self.db.query(User).filter_by(stripe_customer_id=stripe_customer_id).first()
        if not user:
            return

        logger.info(f"Processing subscription deletion for user {user.id}")

        # Suspend User
        user.is_active = False

        # Mark subscription canceled
        sub = None
        if stripe_subscription_id:
            sub = self.db.query(Subscription).filter_by(stripe_subscription_id=stripe_subscription_id).first()

        if not sub:
             # Fallback
             sub = self.db.query(Subscription).filter_by(user_id=user.id).order_by(Subscription.id.desc()).first()

        if sub:
            sub.state = "canceled"
            sub.cancel_requested_at = datetime.utcnow() # Technically already canceled

        self.db.commit()
