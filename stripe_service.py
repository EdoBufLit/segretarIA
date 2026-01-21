import os
import stripe
from dotenv import load_dotenv
from sqlalchemy.orm import Session
from datetime import datetime
from models import User, Subscription, Plan

load_dotenv()

stripe.api_key = os.getenv("STRIPE_SECRET_KEY")

class StripeService:
    @staticmethod
    def create_customer_if_missing(user, db):
        """
        Ensures a Stripe customer exists for the given user.
        Updates user.stripe_customer_id in the DB.
        """
        if user.stripe_customer_id:
             # Use a simple object to mimic the Stripe Customer object structure expected by callers
             class SimpleCustomer:
                 def __init__(self, id):
                     self.id = id
             return SimpleCustomer(user.stripe_customer_id)

        if not user.email:
            raise ValueError("User must have an email address")

        # Search for existing customer by email in Stripe
        existing_customers = stripe.Customer.list(email=user.email, limit=1)
        if existing_customers.data:
            customer = existing_customers.data[0]
        else:
            # Create new customer if not found
            customer = stripe.Customer.create(
                email=user.email,
                metadata={"user_id": str(user.id)}
            )

        # Save to DB
        user.stripe_customer_id = customer.id
        db.add(user)
        db.commit()
        db.refresh(user)

        return customer

    @staticmethod
    def create_checkout_session(user, price_id, db, metadata=None):
        """
        Creates a Stripe Checkout Session for a subscription.
        """
        customer = StripeService.create_customer_if_missing(user, db)

        success_url = os.getenv("STRIPE_SUCCESS_URL")
        cancel_url = os.getenv("STRIPE_CANCEL_URL")

        if not success_url or not cancel_url:
             raise ValueError("STRIPE_SUCCESS_URL and STRIPE_CANCEL_URL must be set in environment variables")

        session_params = {
            "customer": customer.id,
            "line_items": [
                {
                    "price": price_id,
                    "quantity": 1,
                },
            ],
            "mode": "subscription",
            "success_url": success_url,
            "cancel_url": cancel_url,
        }

        if metadata:
            session_params["metadata"] = metadata

        checkout_session = stripe.checkout.Session.create(**session_params)
        return checkout_session

    @staticmethod
    def create_customer_portal_session(user, db):
        """
        Creates a Billing Portal session for the user to manage their subscription.
        """
        customer = StripeService.create_customer_if_missing(user, db)

        # We use STRIPE_SUCCESS_URL as the return_url, assuming it leads back to a useful place (e.g. dashboard).
        # Alternatively, we could use STRIPE_CANCEL_URL or a dedicated STRIPE_PORTAL_RETURN_URL if it existed.
        return_url = os.getenv("STRIPE_SUCCESS_URL")

        if not return_url:
            raise ValueError("STRIPE_SUCCESS_URL must be set to generate a return URL for the portal")

        session = stripe.billing_portal.Session.create(
            customer=customer.id,
            return_url=return_url
        )
        return session

    @staticmethod
    def construct_event(payload, sig_header):
        """
        Verifies the Stripe webhook signature and constructs the event.
        """
        webhook_secret = os.getenv("STRIPE_WEBHOOK_SECRET")
        if not webhook_secret:
            raise ValueError("STRIPE_WEBHOOK_SECRET is not set")

        return stripe.Webhook.construct_event(
            payload, sig_header, webhook_secret
        )

    @staticmethod
    def handle_webhook_event(event, db: Session):
        """
        Dispatches the event to the appropriate handler.
        """
        event_type = event['type']

        if event_type == 'checkout.session.completed':
            StripeService._handle_checkout_session_completed(event, db)
        elif event_type == 'invoice.payment_succeeded':
            StripeService._handle_invoice_payment_succeeded(event, db)
        elif event_type == 'invoice.payment_failed':
            StripeService._handle_invoice_payment_failed(event, db)
        elif event_type == 'customer.subscription.deleted':
            StripeService._handle_subscription_deleted(event, db)
        # Add more handlers as needed
        else:
            # Unhandled event type
            pass

    @staticmethod
    def _handle_checkout_session_completed(event, db: Session):
        session = event['data']['object']

        # We only care about subscription mode
        if session.get('mode') != 'subscription':
            return

        client_reference_id = session.get('client_reference_id') # If we used this
        metadata = session.get('metadata', {})
        user_id_str = metadata.get('user_id')

        stripe_customer_id = session.get('customer')
        stripe_subscription_id = session.get('subscription')

        if not stripe_subscription_id:
             return

        # Retrieve subscription details from Stripe to get period dates and plan
        subscription_obj = stripe.Subscription.retrieve(stripe_subscription_id)
        current_period_start = datetime.utcfromtimestamp(subscription_obj['current_period_start'])
        current_period_end = datetime.utcfromtimestamp(subscription_obj['current_period_end'])

        # Plan info
        price_id = subscription_obj['items']['data'][0]['price']['id']

        # Find user
        user = None
        if user_id_str:
            user = db.query(User).filter(User.id == int(user_id_str)).first()
        elif stripe_customer_id:
            user = db.query(User).filter(User.stripe_customer_id == stripe_customer_id).first()

        if not user:
            # Log error: could not find user
            print(f"Error: User not found for checkout session {session.get('id')}")
            return

        # Update user's stripe_customer_id if missing (idempotency)
        if not user.stripe_customer_id and stripe_customer_id:
            user.stripe_customer_id = stripe_customer_id
            db.add(user)

        # Ensure user is active upon payment
        if not user.is_active:
            user.is_active = True
            db.add(user)

        # Map price_id to internal Plan (assuming we have Plans in DB or mapping logic)
        # For this context, we might check env vars or logic
        # Simple logic: check if plan exists, else use default or create dummy
        # We have a Plan model. Let's find or create a plan based on price_id logic or just update Subscription.

        # Logic to map price_id to Plan.code?
        # Env vars: STRIPE_PRICE_BASIC, STRIPE_PRICE_PRO
        price_basic = os.getenv("STRIPE_PRICE_BASIC")
        price_pro = os.getenv("STRIPE_PRICE_PRO")

        plan_code = "basic" # Default
        if price_id == price_pro:
            plan_code = "pro"
        elif price_id == price_basic:
            plan_code = "basic"

        plan = db.query(Plan).filter(Plan.code == plan_code).first()
        if not plan:
            # Create default plan if missing (should be seeded strictly speaking)
            minutes = 100 if plan_code == 'basic' else 1000 # Example logic
            plan = Plan(code=plan_code, minutes_per_cycle=minutes)
            db.add(plan)
            db.commit()

        # Check for existing subscription (Idempotency)
        existing_sub = db.query(Subscription).filter(Subscription.stripe_subscription_id == stripe_subscription_id).first()

        if existing_sub:
            # Update existing
            existing_sub.state = 'active'
            existing_sub.plan_id = plan.id
            existing_sub.cycle_start = current_period_start
            existing_sub.cycle_end = current_period_end
            existing_sub.stripe_price_id = price_id
            existing_sub.last_payment_status = 'succeeded'
        else:
            # Create new
            # Deactivate other active subscriptions? Usually yes, one active sub per user.
            db.query(Subscription).filter(
                Subscription.user_id == user.id,
                Subscription.state == 'active'
            ).update({"state": "canceled"})

            new_sub = Subscription(
                user_id=user.id,
                plan_id=plan.id,
                state='active',
                cycle_start=current_period_start,
                cycle_end=current_period_end,
                stripe_subscription_id=stripe_subscription_id,
                stripe_price_id=price_id,
                last_payment_status='succeeded'
            )
            db.add(new_sub)

        db.commit()

    @staticmethod
    def _handle_invoice_payment_succeeded(event, db: Session):
        invoice = event['data']['object']
        stripe_subscription_id = invoice.get('subscription')

        if not stripe_subscription_id:
            return

        # Update subscription cycle
        sub = db.query(Subscription).filter(Subscription.stripe_subscription_id == stripe_subscription_id).first()
        if sub:
            # We might want to re-fetch subscription details from Stripe to be sure about dates
            # or trust invoice 'lines' period.
            # Safe bet: retrieve subscription
            try:
                subscription_obj = stripe.Subscription.retrieve(stripe_subscription_id)
                sub.cycle_start = datetime.utcfromtimestamp(subscription_obj['current_period_start'])
                sub.cycle_end = datetime.utcfromtimestamp(subscription_obj['current_period_end'])
                sub.state = subscription_obj['status'] # e.g. active
                sub.last_payment_status = 'paid'

                # Restore service if previously suspended (and payment succeeded)
                if sub.state == 'active' and not sub.user.is_active:
                    sub.user.is_active = True
                    db.add(sub.user)

                db.commit()
            except Exception as e:
                print(f"Error updating subscription {stripe_subscription_id}: {e}")

    @staticmethod
    def _handle_invoice_payment_failed(event, db: Session):
        invoice = event['data']['object']
        stripe_subscription_id = invoice.get('subscription')

        if not stripe_subscription_id:
            return

        sub = db.query(Subscription).filter(Subscription.stripe_subscription_id == stripe_subscription_id).first()
        if sub:
            sub.state = 'past_due'
            sub.last_payment_status = 'failed'

            # Stop service immediately
            if sub.user.is_active:
                sub.user.is_active = False
                db.add(sub.user)

            db.commit()

    @staticmethod
    def _handle_subscription_deleted(event, db: Session):
        stripe_sub = event['data']['object']
        stripe_subscription_id = stripe_sub.get('id')

        sub = db.query(Subscription).filter(Subscription.stripe_subscription_id == stripe_subscription_id).first()
        if sub:
            sub.state = 'canceled'

            # Stop service immediately
            if sub.user.is_active:
                sub.user.is_active = False
                db.add(sub.user)

            db.commit()
