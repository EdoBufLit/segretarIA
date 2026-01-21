from datetime import datetime, timedelta
import math
from sqlalchemy.orm import Session
from models import User, Subscription, UsageEvent, PhoneNumber
from mailer import send_email
import os

class ClientService:
    def __init__(self, db: Session, user: User):
        self.db = db
        self.user = user

    def get_subscription_status(self):
        subscription = self.db.query(Subscription).filter_by(user_id=self.user.id).first()
        if not subscription or subscription.state != "active":
            return {"status": "inactive"}

        usage_events = self.db.query(UsageEvent).filter(
            UsageEvent.user_id == self.user.id,
            UsageEvent.created_at >= subscription.cycle_start,
            UsageEvent.created_at <= subscription.cycle_end,
        ).all()

        minutes_used = math.ceil(sum(event.billed_seconds for event in usage_events) / 60)
        minutes_total = subscription.plan.minutes_per_cycle
        minutes_remaining = max(0, minutes_total - minutes_used)

        return {
            "plan_code": subscription.plan.code,
            "minutes_total": minutes_total,
            "minutes_used": minutes_used,
            "minutes_remaining": minutes_remaining,
            "state": subscription.state,
            "cycle_end": subscription.cycle_end.isoformat(),
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
            send_email(admin_email, subject, body)

        self.db.commit()

        return {"status": "ok", "message": "Subscription cancelled and deprovisioning scheduled."}
