from datetime import datetime, timedelta
import logging
from sqlalchemy.orm import Session
from models import User, Subscription, Plan

logger = logging.getLogger("subscription_service")

def ensure_subscription_for_user(db: Session, user_id: int):
    """
    Ensures that a Subscription record exists and is consistent with the user's state.

    1. Prefer Stripe subscription state if stripe_subscription_id exists and state='active'.
    2. Else fall back to users.subscription_plan (admin-set) if not NONE.
    """
    try:
        user = db.query(User).filter(User.id == user_id).first()
        if not user:
            logger.warning(f"User {user_id} not found during ensure_subscription")
            return

        # 1. Check for active Stripe subscription
        active_stripe_sub = db.query(Subscription).filter(
            Subscription.user_id == user_id,
            Subscription.stripe_subscription_id != None,
            Subscription.state == 'active'
        ).first()

        if active_stripe_sub:
            # Sync user.subscription_plan to match Stripe sub if needed
            if active_stripe_sub.plan and user.subscription_plan != active_stripe_sub.plan.code:
                logger.info(f"Syncing user {user_id} plan from {user.subscription_plan} to {active_stripe_sub.plan.code} (Stripe)")
                user.subscription_plan = active_stripe_sub.plan.code
                db.commit()
            return

        # 2. Fallback to manual plan (User.subscription_plan)
        manual_plan_code = user.subscription_plan
        if not manual_plan_code or manual_plan_code == 'NONE':
            # No manual plan set, nothing to enforce.
            # (Optional: we could cancel any existing manual sub if it exists, but requirements don't strictly ask for it)
            return

        plan = db.query(Plan).filter(Plan.code == manual_plan_code).first()
        if not plan:
            logger.warning(f"Plan code {manual_plan_code} not found in DB")
            return

        # Find existing manual/latest subscription
        # We prioritize a sub that is NOT a stripe sub (stripe_subscription_id IS NULL)
        # OR just take the latest one.

        # Strategy: find latest sub.
        latest_sub = db.query(Subscription).filter(
            Subscription.user_id == user_id
        ).order_by(Subscription.id.desc()).first()

        now = datetime.utcnow()

        if latest_sub:
            # Update existing
            latest_sub.plan_id = plan.id
            latest_sub.state = 'active'
            latest_sub.updated_at = now
            # If we are converting a stripe sub to manual (e.g. stripe cancelled, admin sets manual), clear stripe id
            # latest_sub.stripe_subscription_id = None # Do we want to overwrite? Probably yes if we are taking over.
            # Actually, safer to clear it if we are asserting manual control.

            # Check cycle dates
            if latest_sub.cycle_end < now or not latest_sub.cycle_start:
                # Expired or invalid, reset cycle
                latest_sub.cycle_start = now
                latest_sub.cycle_end = now + timedelta(days=30)

            logger.info(f"Updated subscription {latest_sub.id} for user {user_id} to plan {manual_plan_code} (Manual)")
        else:
            # Create new
            new_sub = Subscription(
                user_id=user_id,
                plan_id=plan.id,
                state='active',
                cycle_start=now,
                cycle_end=now + timedelta(days=30),
                updated_at=now,
                stripe_subscription_id=None
            )
            db.add(new_sub)
            logger.info(f"[USAGE] Created missing subscription for user_id={user_id}")

        db.commit()

    except Exception as e:
        logger.error(f"Error in ensure_subscription_for_user: {e}")
        db.rollback()
