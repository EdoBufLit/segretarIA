from datetime import datetime
import math
from sqlalchemy.orm import Session
from models import User, Subscription, UsageEvent

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
        subscription = self.db.query(Subscription).filter_by(user_id=self.user.id).first()
        if not subscription or subscription.state != "active":
            raise ValueError("No active subscription to cancel")

        subscription.state = "canceled"
        subscription.cancel_requested_at = datetime.utcnow()
        self.db.commit()

        return {"status": "ok", "message": "Subscription cancellation request received."}
