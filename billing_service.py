import math
from datetime import datetime, timedelta
from sqlalchemy import func
from sqlalchemy.orm import Session
from models import User, Agent, Subscription, UsageEvent

class BillingService:
    def __init__(self, db: Session):
        self.db = db

    def calculate_usage_minutes(self, user_id: int, start_date: datetime, end_date: datetime) -> int:
        """
        Calculates total minutes used by a user within a date range.
        Rounds up the total minutes.
        """
        total_seconds = self.db.query(func.sum(UsageEvent.billed_seconds)).filter(
            UsageEvent.user_id == user_id,
            UsageEvent.started_at >= start_date,
            UsageEvent.started_at <= end_date
        ).scalar() or 0

        return math.ceil(total_seconds / 60)

    def meter_call(self, agent_id: str, duration_secs: int, call_id: str, started_at: datetime, ended_at: datetime):
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

        # 2. Find current subscription
        now = datetime.utcnow()
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
        existing_event = self.db.query(UsageEvent).filter_by(call_id=call_id).first()
        if existing_event:
            print(f"Metering skipped: UsageEvent with call_id '{call_id}' already exists.")
            return

        # 4. Create UsageEvent
        usage_event = UsageEvent(
            subscription_id=active_subscription.id,
            user_id=client_user.id,
            agent_id=agent.id,
            billed_seconds=duration_secs,
            call_id=call_id,
            started_at=started_at,
            ended_at=ended_at,
        )
        self.db.add(usage_event)
        self.db.commit()
        print(f"Successfully metered call '{call_id}' for user '{client_user.username}'.")
