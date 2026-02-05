from datetime import datetime, timedelta
from typing import Optional
import math
from sqlalchemy import func
from sqlalchemy.orm import Session
from models import User, Agent, Subscription, UsageEvent
from services.subscription_service import ensure_subscription_for_user

class BillingService:
    def __init__(self, db: Session):
        self.db = db

    def get_minutes_status(self, subscription: Subscription) -> dict:
        if not subscription or not subscription.plan:
            return {
                "minutes_total": 0,
                "minutes_used": 0,
                "minutes_remaining": 0,
                "subscription_id": subscription.id if subscription else None,
            }

        usage_seconds = self.db.query(func.sum(UsageEvent.billed_seconds)) \
            .filter(UsageEvent.subscription_id == subscription.id) \
            .filter(UsageEvent.created_at >= subscription.cycle_start) \
            .filter(UsageEvent.created_at <= subscription.cycle_end) \
            .scalar() or 0

        minutes_used = math.ceil(usage_seconds / 60) if usage_seconds else 0
        minutes_total = subscription.plan.minutes_per_cycle
        minutes_remaining = max(0, minutes_total - minutes_used)

        return {
            "minutes_total": minutes_total,
            "minutes_used": minutes_used,
            "minutes_remaining": minutes_remaining,
            "subscription_id": subscription.id,
        }

    def meter_call(
        self,
        agent_id: str,
        duration_secs: int,
        call_log_id: int,
        started_at: datetime,
        ended_at: datetime,
        call_id: Optional[str] = None,
    ):
        # 1. Resolve tenant from agent_id
        agent = self.db.query(Agent).filter_by(agent_id=agent_id).first()
        if not agent:
            print(f"Metering failed: Agent '{agent_id}' not found.")
            return

        # Get the associated client User
        client_user = self.db.query(User).filter(User.agents.contains(agent)).order_by(User.id).first()
        if not client_user:
            print(f"Metering failed: No client user found for agent '{agent_id}'.")
            return

        # 2. Ensure subscription and find current subscription
        ensure_subscription_for_user(self.db, client_user.id)
        now = datetime.utcnow()
        active_subscription = self.db.query(Subscription).filter(
            Subscription.user_id == client_user.id,
            Subscription.state == "active",
            Subscription.cycle_start <= now,
            Subscription.cycle_end > now
        ).first()

        if not active_subscription:
            if client_user.subscription_plan and client_user.subscription_plan != "NONE":
                ensure_subscription_for_user(self.db, client_user.id)
                active_subscription = self.db.query(Subscription).filter(
                    Subscription.user_id == client_user.id,
                    Subscription.state == "active",
                    Subscription.cycle_start <= now,
                    Subscription.cycle_end > now
                ).first()

            if not active_subscription:
                print(f"Metering failed: No active subscription found for user '{client_user.username}'.")
                return

        # 3. Idempotency check
        existing_event = self.db.query(UsageEvent).filter_by(call_log_id=call_log_id).first()
        if existing_event:
            print(f"Metering skipped: UsageEvent with call_log_id '{call_log_id}' already exists.")
            return

        # 4. Create UsageEvent
        if call_id is None:
            call_id = f"conv_{call_log_id}"
        usage_event = UsageEvent(
            subscription_id=active_subscription.id,
            user_id=client_user.id,
            agent_id=agent.id,
            billed_seconds=duration_secs,
            call_id=call_id,
            call_log_id=call_log_id,
            started_at=started_at,
            ended_at=ended_at,
        )
        self.db.add(usage_event)
        self.db.commit()
        print(f"[USAGE] Inserted usage_event seconds={duration_secs}")
