from datetime import datetime, timedelta
from unittest.mock import MagicMock, patch

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from db import Base
from models import Agent, AgentRouting, PhoneNumber, Plan, Subscription, User
from jobs import eleven_jobs


def _setup_db():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    session_cls = sessionmaker(bind=engine)
    return session_cls()


def test_elevenlabs_job_summarizes_and_enqueues_email():
    db = _setup_db()

    plan = Plan(code="pro", minutes_per_cycle=100)
    user = User(
        username="client",
        email="client@example.com",
        password_hash="hash",
        role="client",
        is_active=True,
        studio_name="Studio",
    )
    agent = Agent(agent_id="agent-1", display_name="Agent One")
    user.agents.append(agent)
    subscription = Subscription(
        user=user,
        plan=plan,
        state="active",
        cycle_start=datetime.utcnow() - timedelta(days=1),
        cycle_end=datetime.utcnow() + timedelta(days=30),
    )
    phone = PhoneNumber(e164="+390000000000", provider="elevenlabs", status="active", user=user)
    routing = AgentRouting(agent_id="agent-1", user=user, is_active=True, phone_number=phone)

    db.add_all([plan, user, agent, subscription, phone, routing])
    db.commit()

    payload = {
        "type": "post_call_transcription",
        "data": {
            "agent_id": "agent-1",
            "metadata": {
                "start_time_unix_secs": 1700000000,
                "call_duration_secs": 12,
                "phone_call": {
                    "call_sid": "CA12345",
                    "number": "+390000000000",
                    "external_number": "+391234567890",
                },
            },
            "transcript": [
                {"role": "user", "message": "Ciao"},
                {"role": "agent", "message": "Buongiorno"},
            ],
        },
    }

    with patch("jobs.eleven_jobs.SessionLocal") as mock_session, \
        patch("jobs.eleven_jobs.get_queue") as mock_get_queue, \
        patch("jobs.eleven_jobs.summarize_call") as mock_summarize:
        mock_session.return_value.__enter__.return_value = db
        mock_session.return_value.__exit__.return_value = None

        mock_queue = MagicMock()
        mock_get_queue.return_value = mock_queue
        mock_summarize.return_value = {"summary": "ok", "urgency": "ignoto"}

        eleven_jobs._process_elevenlabs_event_logic(payload)

    mock_summarize.assert_called_once()
    mock_queue.enqueue.assert_called_once()
    enqueue_args = mock_queue.enqueue.call_args[0]
    assert enqueue_args[0] == eleven_jobs.send_email_job
