from stripe_service import StripeService
from db import SessionLocal
import logging

logger = logging.getLogger("stripe_jobs")

def process_stripe_event_job(event_type: str, data: dict):
    """
    Background job to process Stripe events.
    """
    try:
        logger.info(f"Processing Stripe event: {event_type}")
        with SessionLocal() as db:
            service = StripeService(db)
            service.process_event(event_type, data)
    except Exception as e:
        logger.error(f"Stripe job failed: {e}")
        raise
