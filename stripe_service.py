import stripe
import os
from datetime import datetime, timedelta
from sqlalchemy.orm import Session
from models import User, Subscription, Plan, AuditEvent
import logging
import audit_logger
from mailer import send_email

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
        env_key = f"STRIPE_PRICE_ID_{plan_code.upper()}"
        price_id = os.getenv(env_key)
        if not price_id:
            raise ValueError(f"Configuration error: Missing {env_key}")

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

    def create_customer_portal_session(self, user_id: int, return_url: str):
        # MOCK FOR QA
        if self.api_key == "mock":
            class MockSession:
                url = "http://mock-portal-url.com"
            return MockSession()

        if not self.api_key:
             raise ValueError("Stripe not configured")

        user = self.db.query(User).filter(User.id == user_id).first()
        if not user or not user.stripe_customer_id:
            raise ValueError("User has no Stripe Customer ID")

        try:
            session = stripe.billing_portal.Session.create(
                customer=user.stripe_customer_id,
                return_url=return_url,
            )
            return session
        except Exception as e:
             logger.error(f"Stripe Portal Error: {e}")
             raise

    def verify_webhook_event(self, payload: bytes, sig_header: str):
        """Verifies signature and returns (event_type, data)."""
        # MOCK FOR QA
        if self.webhook_secret == "mock":
             import json
             event = json.loads(payload)
        else:
            if not self.webhook_secret:
                 logger.error("STRIPE_WEBHOOK_SECRET is not set")
                 raise RuntimeError("Server configuration error: missing webhook secret")

            try:
                event = stripe.Webhook.construct_event(
                    payload, sig_header, self.webhook_secret
                )
            except ValueError as e:
                raise ValueError("Invalid payload")
            except stripe.error.SignatureVerificationError as e:
                raise ValueError("Invalid signature")

        event_type = event['type']
        data = event['data']['object']
        return event_type, data

    def process_event(self, event_type: str, data: dict):
        """Processes the event (DB updates)."""
        if event_type == 'checkout.session.completed':
            self._handle_checkout_completed(data)
        elif event_type == 'invoice.payment_succeeded':
            self._handle_payment_succeeded(data)
        elif event_type == 'invoice.payment_failed':
            self._handle_payment_failed(data)
        elif event_type == 'customer.subscription.deleted':
            self._handle_subscription_deleted(data)

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

        # Fetch actual period end from Stripe
        cycle_end = datetime.utcnow() + timedelta(days=30)
        if stripe_subscription_id and self.api_key and self.api_key != "mock":
            try:
                stripe_sub = stripe.Subscription.retrieve(stripe_subscription_id)
                if stripe_sub and stripe_sub.get('current_period_end'):
                    cycle_end = datetime.fromtimestamp(stripe_sub['current_period_end'])
            except Exception as e:
                logger.error(f"Failed to retrieve subscription {stripe_subscription_id}: {e}")

        subscription = self.db.query(Subscription).filter_by(user_id=user_id).first()
        if not subscription:
            subscription = Subscription(
                user_id=user_id,
                plan_id=plan.id,
                state="active",
                cycle_start=datetime.utcnow(),
                cycle_end=cycle_end,
                stripe_subscription_id=stripe_subscription_id,
                stripe_price_id=None
            )
            self.db.add(subscription)
        else:
            subscription.plan_id = plan.id
            subscription.state = "active"
            subscription.cycle_start = datetime.utcnow()
            subscription.cycle_end = cycle_end
            subscription.stripe_subscription_id = stripe_subscription_id

        self.db.commit()

        # Audit Log
        audit_logger.log_audit_event(
            db=self.db,
            actor_type="stripe",
            action="subscription_activated",
            entity_type="subscription",
            entity_id=str(subscription.id),
            meta={
                "stripe_event": "checkout.session.completed",
                "stripe_subscription_id": stripe_subscription_id,
                "plan": plan_code
            },
            admin_username="stripe_webhook",
            target_str=f"user={user.username} plan={plan_code}"
        )

        # Notify Admin (Idempotent)
        self._notify_admin_payment_success(user, plan_code, f"checkout:{session.get('id')}", "Checkout Completed")

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

        # Audit Log
        audit_logger.log_audit_event(
            db=self.db,
            actor_type="stripe",
            action="payment_failed_suspended",
            entity_type="user",
            entity_id=str(user.id),
            meta={
                "stripe_event": "invoice.payment_failed",
                "stripe_customer_id": stripe_customer_id
            },
            admin_username="stripe_webhook",
            target_str=f"user={user.username} suspended"
        )

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

        # Audit Log
        audit_logger.log_audit_event(
            db=self.db,
            actor_type="stripe",
            action="payment_succeeded_restored",
            entity_type="user",
            entity_id=str(user.id),
            meta={
                "stripe_event": "invoice.payment_succeeded",
                "stripe_customer_id": stripe_customer_id
            },
            admin_username="stripe_webhook",
            target_str=f"user={user.username} restored"
        )

        # Notify Admin (Idempotent)
        plan_code = "unknown"
        if sub:
             plan_code = sub.plan.code if sub.plan else "unknown"
        amount_paid = invoice.get("amount_paid", 0) / 100.0
        currency = invoice.get("currency", "eur").upper()

        self._notify_admin_payment_success(
            user,
            plan_code,
            f"invoice:{invoice.get('id')}",
            f"Invoice Paid ({amount_paid} {currency})"
        )

    def _notify_admin_payment_success(self, user: User, plan_code: str, transaction_id: str, context: str):
        """
        Sends an email to admin on successful payment, ensuring idempotency via AuditEvents.
        """
        admin_email = os.getenv("ADMIN_BILLING_EMAIL")
        if not admin_email:
            logger.warning("ADMIN_BILLING_EMAIL not set, skipping notification.")
            return

        # Idempotency Check
        exists = self.db.query(AuditEvent).filter_by(
            action="admin_notification_payment_success",
            entity_id=transaction_id
        ).first()

        if exists:
            logger.info(f"Admin notification already sent for {transaction_id}. Skipping.")
            return

        subject = f"[PAYMENT] Nuovo pagamento: {user.studio_name or user.username} - {plan_code}"
        body = (
            f"<h3>Nuovo Pagamento Ricevuto</h3>"
            f"<ul>"
            f"<li><strong>Cliente:</strong> {user.studio_name} ({user.username})</li>"
            f"<li><strong>Email:</strong> {user.email}</li>"
            f"<li><strong>Piano:</strong> {plan_code}</li>"
            f"<li><strong>Contesto:</strong> {context}</li>"
            f"<li><strong>Riferimento:</strong> {transaction_id}</li>"
            f"</ul>"
        )

        try:
            send_email(admin_email, subject, body)

            # Log Idempotency
            audit_logger.log_audit_event(
                db=self.db,
                actor_type="system",
                action="admin_notification_payment_success",
                entity_type="transaction",
                entity_id=transaction_id,
                meta={"user_id": user.id, "email_to": admin_email}
            )
            logger.info(f"Admin notification sent to {admin_email} for {transaction_id}")
        except Exception as e:
            logger.error(f"Failed to send admin notification email: {e}")

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

        # Audit Log
        audit_logger.log_audit_event(
            db=self.db,
            actor_type="stripe",
            action="subscription_deleted_suspended",
            entity_type="user",
            entity_id=str(user.id),
            meta={
                "stripe_event": "customer.subscription.deleted",
                "stripe_subscription_id": stripe_subscription_id
            },
            admin_username="stripe_webhook",
            target_str=f"user={user.username} canceled"
        )
