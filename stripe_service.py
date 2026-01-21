import os
import stripe
from dotenv import load_dotenv

load_dotenv()

stripe.api_key = os.getenv("STRIPE_SECRET_KEY")

class StripeService:
    @staticmethod
    def create_customer_if_missing(user):
        """
        Ensures a Stripe customer exists for the given user.
        Since we cannot modify the User model to store stripe_customer_id,
        we rely on searching by email.
        """
        if not user.email:
            raise ValueError("User must have an email address")

        # Search for existing customer by email
        existing_customers = stripe.Customer.list(email=user.email, limit=1)
        if existing_customers.data:
            return existing_customers.data[0]

        # Create new customer if not found
        customer = stripe.Customer.create(
            email=user.email,
            metadata={"user_id": str(user.id)}
        )
        return customer

    @staticmethod
    def create_checkout_session(user, price_id, metadata=None):
        """
        Creates a Stripe Checkout Session for a subscription.
        """
        customer = StripeService.create_customer_if_missing(user)

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
    def create_customer_portal_session(user):
        """
        Creates a Billing Portal session for the user to manage their subscription.
        """
        customer = StripeService.create_customer_if_missing(user)

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
