from datetime import datetime, timedelta
from sqlalchemy.orm import Session
from models import User, Agent, Subscription, UsageEvent
from services.subscription_service import ensure_subscription_for_user

class BillingService:
    def __init__(self, db: Session):
        self.db = db

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
        print(f"[USAGE] Inserted usage_event seconds={duration_secs}")
