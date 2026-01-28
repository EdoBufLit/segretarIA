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
    JSON,
    Text,
)
from sqlalchemy.orm import relationship, validates
from db import Base
from services.validators import normalize_phone_number

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
    stripe_customer_id = Column(String, nullable=True)
    created_at = Column(DateTime, default=datetime.datetime.utcnow)
    subscription_plan = Column(String, default='NONE', nullable=False)
    plan_expires_at = Column(DateTime, nullable=True)

    def has_active_plan(self):
        """
        Check if user has an active plan.
        Prioritizes manual expiration date if set.
        Otherwise falls back to checking active Subscription records.
        """
        # 1. Manual Override via plan_expires_at
        if self.plan_expires_at:
            return self.plan_expires_at > datetime.datetime.utcnow()

        # 2. Manual Permanent Plan (if plan is set but no expiration, assume indefinite if not NONE?
        # Or require expiration? Prompt says "plan_expires_at (datetime)".
        # Usually manual plans have expiration. If None, maybe it means fallback to Stripe?
        # Let's check subscriptions relationship.

        # 3. Stripe Subscriptions
        for sub in self.subscriptions:
            if sub.state == 'active':
                return True

        return False

    # Relationships
    subscriptions = relationship("Subscription", back_populates="user")
    usage_events = relationship("UsageEvent", back_populates="user")
    agents = relationship(
        "Agent", secondary=UserAgentAccess, back_populates="users"
    )
    phone_numbers = relationship("PhoneNumber", back_populates="user")
    chat_messages = relationship("ChatMessage", back_populates="user")

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

class AgentSettings(Base):
    __tablename__ = "agent_settings"

    id = Column(Integer, primary_key=True, index=True)
    agent_id = Column(String, unique=True, index=True, nullable=False)
    greeting = Column(String, nullable=True)
    notes = Column(String, nullable=True)
    agent_phone_number_id = Column(String, nullable=True)
    test_phone_number = Column(String, nullable=True)
    fallback_number = Column(String, nullable=True) # For inactive service fallback
    created_at = Column(DateTime, default=datetime.datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.datetime.utcnow, onupdate=datetime.datetime.utcnow)

    @validates("fallback_number", "test_phone_number")
    def validate_phone(self, key, value):
        return normalize_phone_number(value)

class CallLog(Base):
    __tablename__ = "call_logs"

    id = Column(Integer, primary_key=True, index=True)
    agent_id = Column(String, index=True, nullable=False)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=True, index=True)
    timestamp = Column(DateTime, nullable=False, default=datetime.datetime.utcnow)
    text = Column(String, nullable=True)
    status = Column(String, nullable=True)
    raw_data = Column(JSON, nullable=True)

    user = relationship("User")

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
    stripe_subscription_id = Column(String, nullable=True)
    stripe_price_id = Column(String, nullable=True)
    updated_at = Column(DateTime, default=datetime.datetime.utcnow, onupdate=datetime.datetime.utcnow)
    cancel_requested_at = Column(DateTime, nullable=True)

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
    notes = Column(String, nullable=True)
    office_phone_e164 = Column(String, nullable=True)
    timezone = Column(String, nullable=False, default="Europe/Rome")
    open_hours_json = Column(JSON, nullable=False, default={"days": ["Mon", "Tue", "Wed", "Thu", "Fri"], "hours": ["09:00", "17:00"]})
    deprovision_at = Column(DateTime, nullable=True)
    released_at = Column(DateTime, nullable=True)
    notified_at = Column(DateTime, nullable=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    created_at = Column(DateTime, default=datetime.datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.datetime.utcnow, onupdate=datetime.datetime.utcnow)

    user = relationship("User", back_populates="phone_numbers")

    @validates("e164", "office_phone_e164")
    def validate_phone(self, key, value):
        return normalize_phone_number(value)

class AuditEvent(Base):
    __tablename__ = "audit_events"

    id = Column(Integer, primary_key=True, index=True)
    created_at = Column(DateTime, default=datetime.datetime.utcnow)
    actor_type = Column(String, nullable=False)  # 'user', 'system', 'stripe', 'admin'
    actor_user_id = Column(Integer, nullable=True)  # if user/admin
    action = Column(String, nullable=False) # 'login', 'reset_password', 'subscription_updated'
    entity_type = Column(String, nullable=True) # 'user', 'subscription'
    entity_id = Column(String, nullable=True) # ID of the entity
    meta_json = Column(JSON, nullable=True) # Extra details

class AgentRouting(Base):
    __tablename__ = "agent_routing"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    agent_id = Column(String, nullable=False)
    phone_number_id = Column(Integer, ForeignKey("phone_numbers.id"), nullable=True)
    status = Column(String, default="active", nullable=False)  # active, unassigned
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.datetime.utcnow, onupdate=datetime.datetime.utcnow)
    last_event_at = Column(DateTime, nullable=True)

    user = relationship("User")
    phone_number = relationship("PhoneNumber")

class UnassignedEvent(Base):
    __tablename__ = "unassigned_events"

    id = Column(Integer, primary_key=True, index=True)
    agent_id = Column(String, index=True, nullable=True)
    phone_number = Column(String, nullable=True)
    payload = Column(JSON, nullable=True)
    created_at = Column(DateTime, default=datetime.datetime.utcnow)

class PasswordResetToken(Base):
    __tablename__ = "password_reset_tokens"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    token_hash = Column(String, index=True, nullable=False)
    expires_at = Column(DateTime, nullable=False)
    used_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.datetime.utcnow)

    user = relationship("User")

class ChatMessage(Base):
    __tablename__ = "chat_messages"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    sender_type = Column(String, nullable=False) # 'client' or 'admin'
    message = Column(Text, nullable=False)
    read = Column(Boolean, default=False)
    created_at = Column(DateTime, default=datetime.datetime.utcnow)

    user = relationship("User", back_populates="chat_messages")
