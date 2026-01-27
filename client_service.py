from datetime import datetime, timedelta
import math
import logging
from sqlalchemy.orm import Session
from models import User, Subscription, UsageEvent, PhoneNumber, Plan
from mailer import send_email
import os

class ClientService:
    def __init__(self, db: Session, user: User):
        self.db = db
        self.user = user

    def get_subscription_status(self):
        # 1. Check for Active Stripe Subscription
        subscription = self.db.query(Subscription).filter_by(user_id=self.user.id, state="active").first()

        # 2. Check for Manual Plan Override
        manual_active = False
        manual_plan = None

        if self.user.has_active_plan():
             # Check if it's a manual plan (plan set and not NONE)
             # Note: has_active_plan() returns True for active Stripe subs too, so we need to be careful.
             # If subscription is None but has_active_plan is True, it must be manual (or stripe sub state issue, but has_active_plan checks state).
             if not subscription:
                  if self.user.subscription_plan and self.user.subscription_plan != 'NONE':
                       manual_active = True
                       # Fetch Plan details
                       manual_plan = self.db.query(Plan).filter(Plan.code == self.user.subscription_plan).first()

        if not subscription and not manual_active:
            return {"status": "inactive"}

        # Define scope for usage calculation
        cycle_start = None
        cycle_end = None
        minutes_total = 0
        plan_code = "unknown"
        state = "inactive"

        if subscription:
            cycle_start = subscription.cycle_start
            cycle_end = subscription.cycle_end
            minutes_total = subscription.plan.minutes_per_cycle
            plan_code = subscription.plan.code
            state = subscription.state
        elif manual_active and manual_plan:
            # For manual plan, define a virtual cycle.
            # If plan_expires_at is set, maybe cycle ends there?
            # Or we look at last 30 days?
            # Let's assume the cycle ends at plan_expires_at and starts 30 days prior,
            # or just calculate usage from the beginning of time if no start date is tracked?
            # Better: Use the current month as the cycle for display purposes?
            # Or use plan_expires_at as the anchor.

            state = "active"
            plan_code = manual_plan.code
            minutes_total = manual_plan.minutes_per_cycle

            if self.user.plan_expires_at:
                 cycle_end = self.user.plan_expires_at
                 # Assume 30 day cycle ending at expiration?
                 cycle_start = cycle_end - timedelta(days=30)

                 # Adjust if cycle_start is in future relative to now? Unlikely if active.
                 # Adjust if cycle_end is far in future (e.g. year)?
                 # For manual plans, simple usage since 'forever' or 'last 30 days' is safer.
                 # Let's use: Start of current month to End of current month?
                 # Or just use the last 30 days window for metering display?

                 # Let's try to match Stripe logic: Billing cycles.
                 # If manual, we don't have a strict cycle.
                 # Fallback: Count usage from created_at or last 30 days?
                 # Let's use: Last 30 days relative to Now.
                 now = datetime.utcnow()
                 cycle_start = now - timedelta(days=30)
                 cycle_end = self.user.plan_expires_at # Show real expiration
            else:
                 # No expiration (permanent)
                 now = datetime.utcnow()
                 cycle_start = now - timedelta(days=30)
                 cycle_end = now + timedelta(days=30) # Fake end

        # Usage Calculation
        # Note: UsageEvent usually requires subscription_id.
        # If manual plan, we might verify usage differently or look for *any* sub id.
        # But here we just query by user_id and date range.

        query = self.db.query(UsageEvent).filter(
            UsageEvent.user_id == self.user.id
        )

        if cycle_start:
             query = query.filter(UsageEvent.created_at >= cycle_start)
        if cycle_end:
             # Only filter end if it's meaningful (e.g. not far future for permanent)
             # But cycle_end is used for display.
             query = query.filter(UsageEvent.created_at <= cycle_end)

        usage_events = query.all()

        minutes_used = math.ceil(sum(event.billed_seconds for event in usage_events) / 60)
        minutes_remaining = max(0, minutes_total - minutes_used)

        return {
            "plan_code": plan_code,
            "minutes_total": minutes_total,
            "minutes_used": minutes_used,
            "minutes_remaining": minutes_remaining,
            "state": state,
            "cycle_end": cycle_end.isoformat() if cycle_end else None,
        }

    def cancel_subscription(self):
        subscription = self.db.query(Subscription).filter_by(user_id=self.user.id, state="active").first()
        if not subscription:
            raise ValueError("No active subscription to cancel")

        subscription.state = "canceled"
        subscription.cancel_requested_at = datetime.utcnow()

        phone_number = self.db.query(PhoneNumber).filter_by(user_id=self.user.id, provider="ehiweb").first()
        if phone_number:
            phone_number.status = "pending_deprovision"
            phone_number.deprovision_at = datetime.utcnow() + timedelta(days=30)

            admin_email = os.getenv("ADMIN_EMAIL", "admin@example.com")
            subject = f"[CANCEL] Cliente {self.user.studio_name or self.user.username} ha annullato. Numero in disdetta tra 30gg: {phone_number.e164}"
            body = f"<p>Il cliente {self.user.studio_name or self.user.username} (ID: {self.user.id}) ha annullato la sua sottoscrizione.</p><p>Il suo numero <b>{phone_number.e164}</b> è stato schedulato per la disdetta manuale tra 30 giorni.</p>"
            try:
                send_email(admin_email, subject, body)
            except Exception as exc:
                logging.getLogger("client_service").error(
                    "Failed to send cancellation email to %s: %s", admin_email, exc
                )

        self.db.commit()

        return {"status": "ok", "message": "Subscription cancelled and deprovisioning scheduled."}
