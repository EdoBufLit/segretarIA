import stripe
import os
import time
from datetime import datetime, timedelta
from sqlalchemy.orm import Session
from models import User, Subscription, Plan
import logging
import audit_logger
from mailer import send_email

logger = logging.getLogger("stripe_service")
ADMIN_EMAIL = os.getenv("ADMIN_EMAIL")

# Cache for plan prices: {timestamp: float, data: dict}
_plans_cache = {"timestamp": 0, "data": {}}
# Cache for recent payments: {timestamp: float, data: list}
_payments_cache = {"timestamp": 0, "data": []}
# Cache for aggregated metrics: {timestamp: float, data: dict}
_metrics_cache = {"timestamp": 0, "data": {}}

class StripeService:
    def __init__(self, db: Session):
        self.db = db
        self.api_key = os.getenv("STRIPE_SECRET_KEY")
        self.webhook_secret = os.getenv("STRIPE_WEBHOOK_SECRET")
        if self.api_key:
            stripe.api_key = self.api_key
        else:
            logger.warning("STRIPE_SECRET_KEY not set")

    def get_stripe_prices(self):
        """
        Fetches plan prices from Stripe (or cache).
        """
        global _plans_cache
        # TTL 10 minutes
        if time.time() - _plans_cache["timestamp"] < 600 and _plans_cache["data"]:
            return _plans_cache["data"]

        codes = ["starter", "pro", "business"]
        result = {}

        try:
            # Handle Mock Mode
            if self.api_key == "mock":
                 # Return mock data for testing/verification if needed
                 mock_prices = {
                     "starter": {"price_display": "29€", "interval": "month"},
                     "pro": {"price_display": "79€", "interval": "month"},
                     "business": {"price_display": "199€", "interval": "month"},
                 }
                 _plans_cache["data"] = mock_prices
                 _plans_cache["timestamp"] = time.time()
                 logger.info("Loaded Stripe prices (MOCK) for plans: starter/pro/business")
                 return mock_prices

            for code in codes:
                price_id = os.getenv(f"STRIPE_PRICE_ID_{code.upper()}")
                if not price_id:
                    result[code] = {"price_display": "—"}
                    continue

                try:
                    p = stripe.Price.retrieve(price_id, expand=["product"])
                    # Assuming EUR mostly, but handling currency symbol simply
                    curr = p.currency.lower()
                    symbol = "€" if curr == "eur" else "$" if curr == "usd" else curr.upper()

                    amt = p.unit_amount / 100.0
                    if amt.is_integer():
                        price_display = f"{int(amt)}{symbol}"
                    else:
                        price_display = f"{amt:.2f}{symbol}"

                    result[code] = {
                        "price_display": price_display,
                        "interval": p.recurring.interval if p.recurring else "one-time"
                    }
                except Exception as e:
                    logger.error(f"Failed to fetch price for {code} (ID: {price_id}): {e}")
                    result[code] = {"price_display": "—"}

            _plans_cache["data"] = result
            _plans_cache["timestamp"] = time.time()
            logger.info("Loaded Stripe prices for plans: starter/pro/business")
            return result

        except Exception as e:
            logger.error(f"Global error fetching stripe prices: {e}")
            # Return existing cache if available, else empty/dashes
            return _plans_cache.get("data", {c: {"price_display": "—"} for c in codes})

    def get_recent_payments(self, limit=10):
        """
        Fetches recent payments (Charges) from Stripe (or cache).
        """
        global _payments_cache
        # TTL 10 minutes
        if time.time() - _payments_cache["timestamp"] < 600 and _payments_cache["data"]:
            return _payments_cache["data"]

        try:
            # Handle Mock Mode
            if self.api_key == "mock":
                mock_data = []
                for i in range(limit):
                    mock_data.append({
                        "id": f"ch_mock_{i}",
                        "amount": 2900 + (i * 1000),
                        "currency": "eur",
                        "status": "succeeded",
                        "created": int(time.time()) - (i * 86400),
                        "billing_details": {"email": f"user{i}@example.com"}
                    })
                _payments_cache["data"] = mock_data
                _payments_cache["timestamp"] = time.time()
                return mock_data

            charges = stripe.Charge.list(limit=limit)
            data = []
            for c in charges.auto_paging_iter():
                data.append({
                    "id": c.id,
                    "amount": c.amount,
                    "currency": c.currency,
                    "status": c.status,
                    "created": c.created,
                    "billing_details": c.billing_details
                })
                if len(data) >= limit:
                    break

            _payments_cache["data"] = data
            _payments_cache["timestamp"] = time.time()
            return data

        except Exception as e:
            logger.error(f"Error fetching recent payments: {e}")
            return _payments_cache.get("data", [])

    def get_aggregated_metrics(self):
        """
        Calculates approximate MRR and Total Revenue.
        """
        global _metrics_cache
        # TTL 10 minutes
        if time.time() - _metrics_cache["timestamp"] < 600 and _metrics_cache["data"]:
            return _metrics_cache["data"]

        metrics = {"mrr": 0.0, "total_revenue": 0.0}

        try:
            if self.api_key == "mock":
                metrics = {"mrr": 1250.00, "total_revenue": 15400.00}
                _metrics_cache["data"] = metrics
                _metrics_cache["timestamp"] = time.time()
                return metrics

            # 1. Total Revenue (Approx last 100 charges)
            charges = stripe.Charge.list(limit=100, status='succeeded')
            total_rev_cents = sum(c.amount for c in charges.auto_paging_iter())
            metrics["total_revenue"] = total_rev_cents / 100.0

            # 2. MRR (Approx active subs)
            subs = stripe.Subscription.list(limit=100, status='active')
            mrr_cents = 0
            for s in subs.auto_paging_iter():
                # Sum items
                for item in s['items']['data']:
                    mrr_cents += item['price']['unit_amount'] * item['quantity']

            metrics["mrr"] = mrr_cents / 100.0

            _metrics_cache["data"] = metrics
            _metrics_cache["timestamp"] = time.time()
            return metrics

        except Exception as e:
            logger.error(f"Error calculating Stripe metrics: {e}")
            return _metrics_cache.get("data", {"mrr": 0.0, "total_revenue": 0.0})

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
        price_id = os.getenv(f"STRIPE_PRICE_ID_{plan_code.upper()}")
        if not price_id:
            logger.warning(f"Missing price ID for plan {plan_code}, using fallback/mock.")
            # Fallback for testing/mocking
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

    def verify_webhook_event(self, payload: bytes, sig_header: str):
        """Verifies signature and returns (event_type, data)."""
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

        # Sync redundant user fields for quick access
        user.subscription_plan = plan.code
        user.plan_expires_at = subscription.cycle_end
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

        # Notify User
        try:
            subject = f"Piano attivato: {plan_code.title()}"
            minutes_included = plan.minutes_per_cycle
            expiration_date = subscription.cycle_end.strftime("%d/%m/%Y")

            body = f"""
            <p>Ciao {user.username},</p>
            <p>Il tuo piano <strong>{plan_code.title()}</strong> è stato attivato con successo.</p>
            <ul>
                <li><strong>Minuti inclusi:</strong> {minutes_included}</li>
                <li><strong>Scadenza:</strong> {expiration_date}</li>
            </ul>
            <p>Accedi alla tua dashboard per iniziare ad usare il servizio.</p>
            """
            send_email(user.email, subject, "Piano attivato. Vedi HTML.", html_body=body)
            logger.info(f"User notification sent to {user.email}")
        except Exception as e:
            logger.warning(f"Failed to send user notification email: {e}")

        # Notify Admin
        if ADMIN_EMAIL:
            try:
                subject = f"Nuovo abbonamento attivato - {plan_code.upper()} - {user.email}"
                body = f"""
                <p>È stato attivato un nuovo abbonamento.</p>
                <ul>
                    <li><strong>Utente:</strong> {user.username} (ID: {user.id})</li>
                    <li><strong>Email:</strong> {user.email}</li>
                    <li><strong>Piano:</strong> {plan_code}</li>
                    <li><strong>Stripe Customer:</strong> {stripe_customer_id}</li>
                    <li><strong>Stripe Subscription:</strong> {stripe_subscription_id}</li>
                    <li><strong>Data:</strong> {datetime.utcnow().isoformat()}</li>
                </ul>
                """
                send_email(ADMIN_EMAIL, subject, "Nuovo abbonamento. Vedi HTML.", html_body=body)
                logger.info(f"Admin notification sent to {ADMIN_EMAIL}")
            except Exception as e:
                logger.warning(f"Failed to send admin notification email: {e}")

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
        cycle_end_dt = None

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
                        cycle_end_dt = sub.cycle_end

                # Sync subscription plan code if available in metadata or product
                # (Optional, but good for consistency)
        else:
            # Fallback: find past_due subscription
            sub = self.db.query(Subscription).filter_by(user_id=user.id, state="past_due").first()
            if sub:
                sub.state = "active"
                # Extend simply by 30 days if no period data
                sub.cycle_end = datetime.utcnow() + timedelta(days=30)
                cycle_end_dt = sub.cycle_end

        # Sync User Fields
        if cycle_end_dt:
            user.plan_expires_at = cycle_end_dt

        # If subscription object found, ensure plan code matches user.subscription_plan?
        # Only if we are sure. For now, trust the existing logic or update if invoice has plan info.
        # Invoice usually has lines.data[0].plan.id -> we need to map back to code.
        # Skipping plan code update here to avoid complexity/mismatch,
        # assuming checkout or previous setup set it correctly.

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
