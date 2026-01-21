from datetime import datetime, timedelta
from sqlalchemy.orm import Session
from models import User, Agent, Plan, Subscription
from auth import hash_password

class AdminService:
    def __init__(self, db: Session):
        self.db = db

    def get_clients(self):
        return self.db.query(User).filter(User.role == "client").all()

    def create_client(self, username: str, email: str, password: str, studio_name: str) -> User:
        existing_user = self.db.query(User).filter(
            (User.username == username) | (User.email == email)
        ).first()
        if existing_user:
            raise ValueError("Username or email already exists")

        hashed_pw = hash_password(password)
        new_client = User(
            username=username,
            email=email,
            password_hash=hashed_pw,
            studio_name=studio_name,
            role="client",
            is_active=True,
        )
        self.db.add(new_client)
        self.db.commit()
        self.db.refresh(new_client)
        return new_client

    def create_agent(self, agent_id: str, display_name: str, phone_number_id: str = None) -> Agent:
        existing_agent = self.db.query(Agent).filter_by(agent_id=agent_id).first()
        if existing_agent:
            raise ValueError("Agent ID already exists")

        new_agent = Agent(
            agent_id=agent_id,
            display_name=display_name,
            phone_number_id=phone_number_id,
        )
        self.db.add(new_agent)
        self.db.commit()
        self.db.refresh(new_agent)
        return new_agent

    def assign_agent_to_client(self, user_id: int, agent_id: int) -> User:
        client = self.db.query(User).filter(User.id == user_id, User.role == "client").first()
        if not client:
            raise ValueError("Client not found")

        agent = self.db.query(Agent).filter(Agent.id == agent_id).first()
        if not agent:
            raise ValueError("Agent not found")

        client.agents.append(agent)
        self.db.commit()
        self.db.refresh(client)
        return client

    def create_or_update_subscription(self, user_id: int, plan_code: str) -> Subscription:
        client = self.db.query(User).filter(User.id == user_id, User.role == "client").first()
        if not client:
            raise ValueError("Client not found")

        plan = self.db.query(Plan).filter(Plan.code == plan_code).first()
        if not plan:
            raise ValueError("Plan not found")

        subscription = self.db.query(Subscription).filter_by(user_id=user_id).first()

        if subscription:
            # Update existing subscription
            subscription.plan_id = plan.id
            subscription.state = "active"
            subscription.cycle_start = datetime.utcnow()
            subscription.cycle_end = datetime.utcnow() + timedelta(days=30)
        else:
            # Create new subscription
            subscription = Subscription(
                user_id=user_id,
                plan_id=plan.id,
                state="active",
                cycle_start=datetime.utcnow(),
                cycle_end=datetime.utcnow() + timedelta(days=30),
            )
            self.db.add(subscription)

        self.db.commit()
        self.db.refresh(subscription)
        return subscription
