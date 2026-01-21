import datetime
from sqlalchemy import (
    Column,
    Integer,
    String,
    Boolean,
    DateTime,
    ForeignKey,
    Table,
    func,
)
from sqlalchemy.orm import relationship
from db import Base

# Association Table for User <-> Agent many-to-many relationship
UserAgentAccess = Table(
    "user_agent_access",
    Base.metadata,
    Column("user_id", Integer, ForeignKey("users.id"), primary_key=True),
    Column("agent_id", Integer, ForeignKey("agents.id"), primary_key=True),
)

class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    username = Column(String, unique=True, index=True, nullable=False)
    password_hash = Column(String, nullable=False)
    role = Column(String, default="client", nullable=False)  # 'admin' or 'client'
    email = Column(String, unique=True, index=True, nullable=False)
    studio_name = Column(String, nullable=True)
    is_active = Column(Boolean, default=True)
    stripe_customer_id = Column(String, nullable=True, index=True)
    created_at = Column(DateTime, default=datetime.datetime.utcnow)

    # Relationships
    subscriptions = relationship("Subscription", back_populates="user")
    usage_events = relationship("UsageEvent", back_populates="user")
    agents = relationship(
        "Agent", secondary=UserAgentAccess, back_populates="users"
    )
    phone_numbers = relationship("PhoneNumber", back_populates="user")

class Agent(Base):
    __tablename__ = "agents"

    id = Column(Integer, primary_key=True, index=True)
    agent_id = Column(String, unique=True, index=True, nullable=False)
    phone_number_id = Column(String, nullable=True)
    display_name = Column(String, nullable=False)

    # Relationships
    users = relationship(
        "User", secondary=UserAgentAccess, back_populates="agents"
    )
    usage_events = relationship("UsageEvent", back_populates="agent")

class Plan(Base):
    __tablename__ = "plans"

    id = Column(Integer, primary_key=True, index=True)
    code = Column(String, unique=True, index=True, nullable=False)
    minutes_per_cycle = Column(Integer, nullable=False)
    is_active = Column(Boolean, default=True)

    # Relationship
    subscriptions = relationship("Subscription", back_populates="plan")

class Subscription(Base):
    __tablename__ = "subscriptions"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    plan_id = Column(Integer, ForeignKey("plans.id"), nullable=False)
    state = Column(String, nullable=False)  # e.g., 'active', 'canceled', 'past_due'
    cycle_start = Column(DateTime, nullable=False)
    cycle_end = Column(DateTime, nullable=False)
    updated_at = Column(DateTime, default=datetime.datetime.utcnow, onupdate=datetime.datetime.utcnow)
    cancel_requested_at = Column(DateTime, nullable=True)

    # Stripe metadata
    stripe_subscription_id = Column(String, nullable=True, unique=True, index=True)
    stripe_price_id = Column(String, nullable=True, index=True)
    last_payment_status = Column(String, nullable=True)

    # Relationships
    user = relationship("User", back_populates="subscriptions")
    plan = relationship("Plan", back_populates="subscriptions")
    usage_events = relationship("UsageEvent", back_populates="subscription")

class UsageEvent(Base):
    __tablename__ = "usage_events"

    id = Column(Integer, primary_key=True, index=True)
    subscription_id = Column(Integer, ForeignKey("subscriptions.id"), nullable=False)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    agent_id = Column(Integer, ForeignKey("agents.id"), nullable=False)
    call_id = Column(String, unique=True, nullable=True)
    started_at = Column(DateTime, nullable=False)
    ended_at = Column(DateTime, nullable=False)
    billed_seconds = Column(Integer, nullable=False)
    created_at = Column(DateTime, default=datetime.datetime.utcnow)

    # Relationships
    subscription = relationship("Subscription", back_populates="usage_events")
    user = relationship("User", back_populates="usage_events")
    agent = relationship("Agent", back_populates="usage_events")

class PhoneNumber(Base):
    __tablename__ = "phone_numbers"

    id = Column(Integer, primary_key=True, index=True)
    e164 = Column(String, unique=True, index=True, nullable=False)
    provider = Column(String, nullable=False, default="ehiweb")
    monthly_cost_cents = Column(Integer, nullable=False, default=200)
    status = Column(String, nullable=False, default="active") # active, pending_deprovision, released
    deprovision_at = Column(DateTime, nullable=True)
    released_at = Column(DateTime, nullable=True)
    notified_at = Column(DateTime, nullable=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    created_at = Column(DateTime, default=datetime.datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.datetime.utcnow, onupdate=datetime.datetime.utcnow)

    user = relationship("User", back_populates="phone_numbers")
