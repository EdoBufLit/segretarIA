import stripe
import os
import time
from datetime import datetime, timedelta
from typing import Any, Dict, Optional
from sqlalchemy.orm import Session
from models import User, Subscription, Plan
import logging
import audit_logger
from mailer import send_email
from services.subscription_service import ensure_subscription_for_user

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

    def _safe_get(self, obj: Any, key: str, default: Any = None) -> Any:
        if obj is None:
            return default
        if hasattr(obj, "get"):
            return obj.get(key, default)
        return getattr(obj, key, default)

    def _normalize_plan_code(self, code: Optional[str]) -> Optional[str]:
        if not code:
            return None
        value = str(code).strip().lower()
        if value in ("starter", "pro", "business"):
            return value
        return None

    def _price_id_map(self) -> Dict[str, str]:
        mapping = {
            os.getenv("STRIPE_PRICE_ID_STARTER"): "starter",
            os.getenv("STRIPE_PRICE_ID_PRO"): "pro",
            os.getenv("STRIPE_PRICE_ID_BUSINESS"): "business",
        }
        return {k: v for k, v in mapping.items() if k}

    def _resolve_plan_code(
        self,
        price_id: Optional[str] = None,
        price_obj: Any = None,
        product_obj: Any = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> Optional[str]:
        # 1) Explicit metadata
        if metadata:
            code = self._normalize_plan_code(metadata.get("plan_code") or metadata.get("plan"))
            if code:
                return code

        for obj in (price_obj, product_obj):
            meta = self._safe_get(obj, "metadata", {}) if obj is not None else {}
            if isinstance(meta, dict):
                code = self._normalize_plan_code(meta.get("plan_code") or meta.get("plan"))
                if code:
                    return code

        # 2) Env price ID mapping
        mapped = self._price_id_map().get(price_id) if price_id else None
        if mapped:
            return mapped

        # 3) Product name heuristic (last resort)
        product_name = self._safe_get(product_obj, "name") or self._safe_get(price_obj, "nickname")
        if product_name:
            lowered = str(product_name).strip().lower()
            for code in ("starter", "pro", "business"):
                if code in lowered:
                    return code
        return None

    def _find_or_create_subscription(
        self,
        user: User,
        plan_code: Optional[str],
        stripe_subscription_id: Optional[str],
        stripe_price_id: Optional[str],
        state: Optional[str],
        period_start: Optional[datetime],
        period_end: Optional[datetime],
    ) -> Optional[Subscription]:
        subscription = None
        if stripe_subscription_id:
            subscription = self.db.query(Subscription).filter_by(
                stripe_subscription_id=stripe_subscription_id
            ).first()
        if not subscription:
            subscription = self.db.query(Subscription).filter_by(
                user_id=user.id
            ).order_by(Subscription.id.desc()).first()

        plan = None
        if plan_code:
            plan = self.db.query(Plan).filter(Plan.code == plan_code).first()
            if not plan:
                logger.warning("Plan code %s not found in DB.", plan_code)

        if not subscription:
            if not plan:
                logger.error("Cannot create subscription without valid plan.")
                return None
            subscription = Subscription(
                user_id=user.id,
                plan_id=plan.id,
                state=state or "active",
                cycle_start=period_start or datetime.utcnow(),
                cycle_end=period_end or (datetime.utcnow() + timedelta(days=30)),
                stripe_subscription_id=stripe_subscription_id,
                stripe_price_id=stripe_price_id,
            )
            self.db.add(subscription)
        else:
            if plan:
                subscription.plan_id = plan.id
            if state:
                subscription.state = state
            if period_start:
                subscription.cycle_start = period_start
            if period_end:
                subscription.cycle_end = period_end
            if stripe_subscription_id:
                subscription.stripe_subscription_id = stripe_subscription_id
            if stripe_price_id:
                subscription.stripe_price_id = stripe_price_id

        return subscription

    def _map_stripe_status(self, status: Optional[str]) -> Optional[str]:
        if not status:
            return None
        status = status.lower()
        if status in ("active", "trialing"):
            return "active"
        if status in ("past_due", "unpaid", "incomplete"):
            return "past_due"
        if status in ("canceled", "incomplete_expired"):
            return "canceled"
        return None
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
                     "starter": {
                         "price_display": "29€",
                         "currency": "eur",
                         "interval": "month",
                         "product_name": "Starter",
                         "description": "Per chi inizia.",
                         "marketing_features": ["Assistente IA H24", "Report via Email", "Supporto Standard"],
                     },
                     "pro": {
                         "price_display": "79€",
                         "currency": "eur",
                         "interval": "month",
                         "product_name": "Pro",
                         "description": "Il piu scelto dai professionisti.",
                         "marketing_features": ["Tutto incluso nel Starter", "Analisi Chiamate", "Priorita Supporto"],
                     },
                     "business": {
                         "price_display": "199€",
                         "currency": "eur",
                         "interval": "month",
                         "product_name": "Business",
                         "description": "Per aziende strutturate.",
                         "marketing_features": ["Minuti elevati", "API Access", "Account Manager"],
                     },
                 }
                 _plans_cache["data"] = mock_prices
                 _plans_cache["timestamp"] = time.time()
                 logger.info("Loaded Stripe prices (MOCK) for plans: starter/pro/business")
                 return mock_prices

            for code in codes:
                price_id = os.getenv(f"STRIPE_PRICE_ID_{code.upper()}")
                if not price_id:
                    result[code] = {
                        "price_display": "—",
                        "currency": None,
                        "interval": "month",
                        "product_name": None,
                        "description": "",
                        "marketing_features": [],
                    }
                    continue

                try:
                    p = stripe.Price.retrieve(price_id, expand=["product"])
                    # Assuming EUR mostly, but handling currency symbol simply
                    curr = (p.currency or "").lower()
                    symbol = "€" if curr == "eur" else "$" if curr == "usd" else curr.upper()

                    amt = p.unit_amount / 100.0
                    if amt.is_integer():
                        price_display = f"{int(amt)}{symbol}"
                    else:
                        price_display = f"{amt:.2f}{symbol}"

                    product_data = p.product or {}
                    if isinstance(product_data, str):
                        product_data = {}

                    product_name = product_data.get("name") if hasattr(product_data, "get") else None
                    description_raw = product_data.get("description") if hasattr(product_data, "get") else None
                    description = description_raw.strip() if isinstance(description_raw, str) else ""

                    raw_features = product_data.get("marketing_features") if hasattr(product_data, "get") else []
                    marketing_features = []
                    for feature in raw_features or []:
                        feature_name = None
                        if hasattr(feature, "get"):
                            feature_name = feature.get("name")
                        elif isinstance(feature, str):
                            feature_name = feature
                        if feature_name:
                            marketing_features.append(str(feature_name))

                    if marketing_features:
                        logger.info(
                            "Loaded %d marketing_features for plan %s",
                            len(marketing_features),
                            code,
                        )

                    result[code] = {
                        "price_display": price_display,
                        "currency": curr,
                        "interval": p.recurring.interval if p.recurring else "one-time",
                        "product_name": product_name,
                        "description": description,
                        "marketing_features": marketing_features,
                    }
                except Exception as e:
                    logger.error(f"Failed to fetch price for {code} (ID: {price_id}): {e}")
                    result[code] = {
                        "price_display": "—",
                        "currency": None,
                        "interval": "month",
                        "product_name": None,
                        "description": "",
                        "marketing_features": [],
                    }

            _plans_cache["data"] = result
            _plans_cache["timestamp"] = time.time()
            logger.info("Loaded Stripe prices for plans: starter/pro/business")
            return result

        except Exception as e:
            logger.error(f"Global error fetching stripe prices: {e}")
            # Return existing cache if available, else empty/dashes
            return _plans_cache.get(
                "data",
                {
                    c: {
                        "price_display": "—",
                        "currency": None,
                        "interval": "month",
                        "product_name": None,
                        "description": "",
                        "marketing_features": [],
                    }
                    for c in codes
                },
            )

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
                subscription_data={
                    "metadata": {
                        "plan_code": plan_code,
                        "user_id": str(user.id),
                    }
                },
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
        elif event_type in ("customer.subscription.created", "customer.subscription.updated"):
            self._handle_subscription_upsert(data, event_type)
        elif event_type in ("invoice.paid", "invoice.payment_succeeded"):
            self._handle_invoice_paid(data)
        elif event_type == 'invoice.payment_failed':
            self._handle_payment_failed(data)
        elif event_type == 'customer.subscription.deleted':
            self._handle_subscription_deleted(data)

    def _handle_checkout_completed(self, session):
        user_id_str = session.get('client_reference_id')
        if not user_id_str:
            logger.error("No client_reference_id in session")
            return

        user_id = int(user_id_str)
        stripe_customer_id = session.get('customer')
        stripe_subscription_id = session.get('subscription')
        payment_status = session.get('payment_status')
        plan_code_hint = self._normalize_plan_code(session.get('metadata', {}).get('plan_code'))

        logger.info(
            "Processing checkout success for user %s (subscription %s).",
            user_id,
            stripe_subscription_id,
        )

        user = self.db.query(User).filter(User.id == user_id).first()
        if not user:
            logger.error("User %s not found", user_id)
            return

        if stripe_customer_id:
            user.stripe_customer_id = stripe_customer_id

        stripe_subscription = None
        if stripe_subscription_id and self.api_key and self.api_key != "mock":
            try:
                stripe_subscription = stripe.Subscription.retrieve(
                    stripe_subscription_id,
                    expand=["items.data.price.product"],
                )
            except Exception as e:
                logger.warning("Failed to retrieve Stripe subscription %s: %s", stripe_subscription_id, e)

        price_obj = None
        product_obj = None
        price_id = None
        status = None
        period_start = None
        period_end = None

        if stripe_subscription:
            items = self._safe_get(stripe_subscription, "items", {}).get("data", [])
            if items:
                price_obj = self._safe_get(items[0], "price")
                if isinstance(price_obj, str):
                    price_id = price_obj
                    price_obj = None
                else:
                    price_id = self._safe_get(price_obj, "id")
                    product_obj = self._safe_get(price_obj, "product")
            status = self._map_stripe_status(self._safe_get(stripe_subscription, "status"))
            start_ts = self._safe_get(stripe_subscription, "current_period_start")
            end_ts = self._safe_get(stripe_subscription, "current_period_end")
            if start_ts:
                period_start = datetime.fromtimestamp(start_ts)
            if end_ts:
                period_end = datetime.fromtimestamp(end_ts)

        plan_code = self._resolve_plan_code(
            price_id=price_id,
            price_obj=price_obj,
            product_obj=product_obj,
            metadata=session.get("metadata"),
        ) or plan_code_hint

        state = status
        if not state and payment_status in ("paid", "no_payment_required"):
            state = "active"
        elif not state and payment_status == "unpaid":
            state = "past_due"

        if state:
            user.is_active = state == "active"

        subscription = self._find_or_create_subscription(
            user=user,
            plan_code=plan_code,
            stripe_subscription_id=stripe_subscription_id,
            stripe_price_id=price_id,
            state=state or "active",
            period_start=period_start,
            period_end=period_end,
        )

        if not subscription:
            logger.error("Unable to upsert subscription for user %s after checkout.", user.id)
            self.db.rollback()
            return

        # Sync redundant user fields for quick access
        user.subscription_plan = plan.code
        user.plan_expires_at = subscription.cycle_end
        self.db.commit()

        # Ensure Subscription Sync
        ensure_subscription_for_user(self.db, user.id)

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

    def _handle_subscription_upsert(self, subscription, event_type: str = "customer.subscription.updated"):
        stripe_customer_id = subscription.get("customer")
        if not stripe_customer_id:
            logger.error("No customer ID in subscription event")
            return

        user = self.db.query(User).filter_by(stripe_customer_id=stripe_customer_id).first()
        if not user:
            metadata = subscription.get("metadata", {}) if isinstance(subscription, dict) else {}
            user_id = metadata.get("user_id") or metadata.get("client_reference_id")
            if user_id:
                user = self.db.query(User).filter(User.id == int(user_id)).first()

        if not user:
            logger.error(f"User not found for stripe_customer_id {stripe_customer_id}")
            return

        if stripe_customer_id and not user.stripe_customer_id:
            user.stripe_customer_id = stripe_customer_id

        stripe_subscription_id = subscription.get("id")
        items = subscription.get("items", {}).get("data", [])
        price_obj = None
        product_obj = None
        price_id = None
        if items:
            price_obj = items[0].get("price")
            if isinstance(price_obj, str):
                price_id = price_obj
                price_obj = None
            else:
                price_id = self._safe_get(price_obj, "id")
                product_obj = self._safe_get(price_obj, "product")

        plan_code = self._resolve_plan_code(
            price_id=price_id,
            price_obj=price_obj,
            product_obj=product_obj,
            metadata=subscription.get("metadata"),
        )

        state = self._map_stripe_status(subscription.get("status"))
        start_ts = subscription.get("current_period_start")
        end_ts = subscription.get("current_period_end")
        period_start = datetime.fromtimestamp(start_ts) if start_ts else None
        period_end = datetime.fromtimestamp(end_ts) if end_ts else None

        if state:
            user.is_active = state == "active"

        subscription_row = self._find_or_create_subscription(
            user=user,
            plan_code=plan_code,
            stripe_subscription_id=stripe_subscription_id,
            stripe_price_id=price_id,
            state=state or "active",
            period_start=period_start,
            period_end=period_end,
        )

        if not subscription_row:
            logger.error("Failed to upsert subscription for user %s", user.id)
            self.db.rollback()
            return

        self.db.commit()

        audit_logger.log_audit_event(
            db=self.db,
            actor_type="stripe",
            action="subscription_synced",
            entity_type="subscription",
            entity_id=str(subscription_row.id),
            meta={
                "stripe_event": event_type,
                "stripe_subscription_id": stripe_subscription_id,
                "plan": plan_code,
                "state": state,
            },
            admin_username="stripe_webhook",
            target_str=f"user={user.username} plan={plan_code}",
        )

    def _handle_invoice_paid(self, invoice):
        stripe_customer_id = invoice.get("customer")
        if not stripe_customer_id:
            logger.error("No customer ID in invoice")
            return

        user = self.db.query(User).filter_by(stripe_customer_id=stripe_customer_id).first()
        if not user:
            metadata = invoice.get("metadata", {}) if isinstance(invoice, dict) else {}
            user_id = metadata.get("user_id") or metadata.get("client_reference_id")
            if user_id:
                user = self.db.query(User).filter(User.id == int(user_id)).first()

        if not user:
            logger.error(f"User with stripe_customer_id {stripe_customer_id} not found")
            return

        if stripe_customer_id and not user.stripe_customer_id:
            user.stripe_customer_id = stripe_customer_id

        stripe_subscription_id = invoice.get("subscription")
        lines = invoice.get("lines", {}).get("data", [])
        price_obj = None
        product_obj = None
        price_id = None
        period_start = None
        period_end = None

        if lines:
            first_line = lines[0]
            price_obj = first_line.get("price")
            if isinstance(price_obj, str):
                price_id = price_obj
                price_obj = None
            else:
                price_id = self._safe_get(price_obj, "id")
                product_obj = self._safe_get(price_obj, "product")

            period = first_line.get("period", {})
            start_ts = period.get("start")
            end_ts = period.get("end")
            period_start = datetime.fromtimestamp(start_ts) if start_ts else None
            period_end = datetime.fromtimestamp(end_ts) if end_ts else None

        plan_code = self._resolve_plan_code(
            price_id=price_id,
            price_obj=price_obj,
            product_obj=product_obj,
            metadata=invoice.get("metadata"),
        )

        user.is_active = True

        subscription_row = self._find_or_create_subscription(
            user=user,
            plan_code=plan_code,
            stripe_subscription_id=stripe_subscription_id,
            stripe_price_id=price_id,
            state="active",
            period_start=period_start,
            period_end=period_end,
        )

        if not subscription_row:
            logger.error("Failed to upsert subscription for user %s", user.id)
            self.db.rollback()
            return

        self.db.commit()

        audit_logger.log_audit_event(
            db=self.db,
            actor_type="stripe",
            action="payment_succeeded_restored",
            entity_type="user",
            entity_id=str(user.id),
            meta={
                "stripe_event": "invoice.paid",
                "stripe_customer_id": stripe_customer_id,
                "stripe_subscription_id": stripe_subscription_id,
                "plan": plan_code,
            },
            admin_username="stripe_webhook",
            target_str=f"user={user.username} restored",
        )

    def _handle_payment_failed(self, invoice):
        stripe_customer_id = invoice.get('customer')
        if not stripe_customer_id:
            logger.error("No customer ID in invoice")
            return

        user = self.db.query(User).filter_by(stripe_customer_id=stripe_customer_id).first()
        if not user:
            metadata = invoice.get("metadata", {}) if isinstance(invoice, dict) else {}
            user_id = metadata.get("user_id") or metadata.get("client_reference_id")
            if user_id:
                user = self.db.query(User).filter(User.id == int(user_id)).first()

        if not user:
            logger.error(f"User with stripe_customer_id {stripe_customer_id} not found")
            return

        if stripe_customer_id and not user.stripe_customer_id:
            user.stripe_customer_id = stripe_customer_id

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
                sub.stripe_subscription_id = subscription_id
        else:
            # Fallback: update user's active subscription
            sub = self.db.query(Subscription).filter_by(user_id=user.id, state="active").first()
            if sub:
                sub.state = "past_due"

        # Update stripe_price_id if available
        lines = invoice.get("lines", {}).get("data", [])
        if sub and lines:
            price_obj = lines[0].get("price")
            if isinstance(price_obj, str):
                sub.stripe_price_id = price_obj
            elif price_obj:
                sub.stripe_price_id = price_obj.get("id")

        self.db.commit()

        # Ensure Subscription Sync
        ensure_subscription_for_user(self.db, user.id)

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

        # Ensure Subscription Sync
        ensure_subscription_for_user(self.db, user.id)

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
            metadata = subscription.get("metadata", {}) if isinstance(subscription, dict) else {}
            user_id = metadata.get("user_id") or metadata.get("client_reference_id")
            if user_id:
                user = self.db.query(User).filter(User.id == int(user_id)).first()

        if not user:
            return

        if stripe_customer_id and not user.stripe_customer_id:
            user.stripe_customer_id = stripe_customer_id

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

        # Ensure Subscription Sync
        ensure_subscription_for_user(self.db, user.id)

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
