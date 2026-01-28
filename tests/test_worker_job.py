
import json
import uuid
import os
from unittest.mock import MagicMock, patch
from datetime import datetime, timedelta
from sqlalchemy.exc import IntegrityError
from db import SessionLocal
from models import Agent, User, UsageEvent, PhoneNumber, AgentRouting, UnassignedEvent, Subscription, Plan, CallLog
from jobs.eleven_jobs import process_elevenlabs_event_job

# Mocks
MOCK_PAYLOAD = {
    "type": "post_call_transcription",
    "data": {
        "agent_id": "test_agent_id",
        "metadata": {
            "start_time_unix_secs": 1700000000,
            "call_duration_secs": 60,
            "phone_call": {
                "call_sid": "test_call_id_unique",
                "number": "+390000000000",
                "external_number": "+393331234567"
            }
        },
        "transcript": [
            {"role": "user", "message": "Ciao"},
            {"role": "agent", "message": "Buongiorno"}
        ]
    }
}

def setup_test_db(db):
    # Setup dependencies
    # Plan
    plan = Plan(code="test_plan", minutes_per_cycle=1000)
    db.add(plan)
    db.flush()

    # User
    user = User(username="testuser", email="test@example.com", password_hash="hash", role="client", is_active=True, studio_name="Test Studio")
    db.add(user)
    db.flush()

    # Subscription
    sub = Subscription(
        user_id=user.id,
        plan_id=plan.id,
        state="active",
        cycle_start=datetime.utcnow() - timedelta(days=1),
        cycle_end=datetime.utcnow() + timedelta(days=30)
    )
    db.add(sub)
    db.flush()

    # Agent
    agent = Agent(agent_id="test_agent_id", display_name="Test Agent")
    db.add(agent)
    db.flush()

    # Routing (active)
    routing = AgentRouting(
        user_id=user.id,
        agent_id=agent.agent_id,
        status="active",
        is_active=True
    )
    db.add(routing)
    db.flush()

    # Link
    from sqlalchemy import text
    db.execute(
        text("INSERT INTO user_agent_access (user_id, agent_id) VALUES (:uid, :aid)"),
        {"uid": user.id, "aid": agent.id}
    )
    db.commit()
    return user, agent

def test_process_elevenlabs_event_job_success():
    """Test happy path: valid user, sub, agent -> locks, processes, sends email."""
    # We mock get_queue and OpenAI to avoid external calls
    with patch("jobs.eleven_jobs.SessionLocal") as MockSession, \
         patch("jobs.eleven_jobs.get_queue") as mock_get_queue, \
         patch("jobs.eleven_jobs.summarize_call") as mock_summarize:

        # In-memory SQLite for logic
        from sqlalchemy import create_engine
        from sqlalchemy.orm import sessionmaker
        from db import Base

        engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(engine)
        Session = sessionmaker(bind=engine)
        db = Session()

        setup_test_db(db)

        # Mock SessionLocal to return our in-memory DB session
        # We need a context manager behavior
        MockSession.return_value.__enter__.return_value = db
        MockSession.return_value.__exit__.return_value = None

        mock_summarize.return_value = {"summary": "Test summary", "urgency": "media"}
        mock_queue_instance = MagicMock()
        mock_get_queue.return_value = mock_queue_instance

        # RUN
        process_elevenlabs_event_job(MOCK_PAYLOAD)

        # Check DB for UsageEvent (Lock)
        call_log = db.query(CallLog).filter_by(agent_id="test_agent_id").first()
        assert call_log is not None
        usage = db.query(UsageEvent).filter_by(call_log_id=call_log.id).first()
        assert usage is not None
        assert usage.billed_seconds == 60

        # Check Email Enqueued
        mock_queue_instance.enqueue.assert_called_once()

        # Check OpenAI called
        mock_summarize.assert_called_once()

def test_process_elevenlabs_event_job_idempotency():
    """Test idempotency: duplicate call_id should not trigger OpenAI or Email."""
    with patch("jobs.eleven_jobs.SessionLocal") as MockSession, \
         patch("jobs.eleven_jobs.get_queue") as mock_get_queue, \
         patch("jobs.eleven_jobs.summarize_call") as mock_summarize:

        from sqlalchemy import create_engine
        engine = create_engine("sqlite:///:memory:")
        from db import Base
        Base.metadata.create_all(engine)
        from sqlalchemy.orm import sessionmaker
        Session = sessionmaker(bind=engine)
        db = Session()

        user, agent = setup_test_db(db)
        sub = db.query(Subscription).first()

        # PRE-EXISTING LOCK (UsageEvent)
        call_log = CallLog(
            agent_id=agent.agent_id,
            user_id=user.id,
            timestamp=datetime.utcnow(),
            text="Test",
            status="success",
            raw_data={"data": {"call_id": "test_call_id_unique"}},
        )
        db.add(call_log)
        db.flush()

        usage = UsageEvent(
            subscription_id=sub.id,
            user_id=user.id,
            agent_id=agent.id,
            call_log_id=call_log.id,
            started_at=datetime.utcnow(),
            ended_at=datetime.utcnow(),
            billed_seconds=60
        )
        db.add(usage)
        db.commit()

        MockSession.return_value.__enter__.return_value = db
        MockSession.return_value.__exit__.return_value = None

        mock_queue_instance = MagicMock()
        mock_get_queue.return_value = mock_queue_instance

        # RUN (Duplicate)
        process_elevenlabs_event_job(MOCK_PAYLOAD)

        # Check: No Email, No OpenAI
        mock_queue_instance.enqueue.assert_not_called()
        mock_summarize.assert_not_called()

def test_process_elevenlabs_event_job_no_email():
    """Test scenario where user has no email: logic should skip email sending but process usage."""
    with patch("jobs.eleven_jobs.SessionLocal") as MockSession, \
         patch("jobs.eleven_jobs.get_queue") as mock_get_queue, \
         patch("jobs.eleven_jobs.summarize_call") as mock_summarize, \
         patch("jobs.eleven_jobs.logger") as mock_logger:

        from sqlalchemy import create_engine
        engine = create_engine("sqlite:///:memory:")
        from db import Base
        Base.metadata.create_all(engine)
        from sqlalchemy.orm import sessionmaker
        Session = sessionmaker(bind=engine)
        db = Session()

        user, agent = setup_test_db(db)
        # Force user email to empty string (DB has nullable=False)
        user.email = ""
        db.commit()

        MockSession.return_value.__enter__.return_value = db
        MockSession.return_value.__exit__.return_value = None

        mock_summarize.return_value = {"summary": "Test summary", "urgency": "media"}
        mock_queue_instance = MagicMock()
        mock_get_queue.return_value = mock_queue_instance

        # RUN
        process_elevenlabs_event_job(MOCK_PAYLOAD)

        # Check DB for UsageEvent (Lock) - Should still be created
        call_log = db.query(CallLog).filter_by(agent_id="test_agent_id").first()
        assert call_log is not None
        usage = db.query(UsageEvent).filter_by(call_log_id=call_log.id).first()
        assert usage is not None
        assert usage.billed_seconds == 60

        # Check Email Enqueued - SHOULD BE 0
        mock_queue_instance.enqueue.assert_not_called()

        # OpenAI might still be called (it's called before email check in the code)
        mock_summarize.assert_called_once()

        # Check Logging
        # Verify that we logged the warning about skipping email
        warning_calls = [call[0][0] for call in mock_logger.warning.call_args_list]
        assert any("Skipping email" in str(arg) for arg in warning_calls)

def test_process_elevenlabs_event_job_no_studio_name():
    """Test scenario where user has no studio_name: logic should skip email sending."""
    with patch("jobs.eleven_jobs.SessionLocal") as MockSession, \
         patch("jobs.eleven_jobs.get_queue") as mock_get_queue, \
         patch("jobs.eleven_jobs.summarize_call") as mock_summarize, \
         patch("jobs.eleven_jobs.logger") as mock_logger:

        from sqlalchemy import create_engine
        engine = create_engine("sqlite:///:memory:")
        from db import Base
        Base.metadata.create_all(engine)
        from sqlalchemy.orm import sessionmaker
        Session = sessionmaker(bind=engine)
        db = Session()

        user, agent = setup_test_db(db)
        # Set studio_name to None/Empty
        user.studio_name = None
        db.commit()

        MockSession.return_value.__enter__.return_value = db
        MockSession.return_value.__exit__.return_value = None

        mock_summarize.return_value = {"summary": "Test summary", "urgency": "media"}
        mock_queue_instance = MagicMock()
        mock_get_queue.return_value = mock_queue_instance

        # RUN
        process_elevenlabs_event_job(MOCK_PAYLOAD)

        # Check DB for UsageEvent (Lock) - Should still be created
        call_log = db.query(CallLog).filter_by(agent_id="test_agent_id").first()
        assert call_log is not None
        usage = db.query(UsageEvent).filter_by(call_log_id=call_log.id).first()
        assert usage is not None

        # Check Email Enqueued - SHOULD BE CALLED (Fallback logic)
        mock_queue_instance.enqueue.assert_called_once()

        # Check Logging
        # Verify that we DID NOT log the warning about missing studio_name
        warning_calls = [call[0][0] for call in mock_logger.warning.call_args_list]
        assert not any("Missing studio_name" in str(arg) for arg in warning_calls)

if __name__ == "__main__":
    # Manually run tests if executed directly
    from sqlalchemy import create_engine
    test_process_elevenlabs_event_job_success()
    test_process_elevenlabs_event_job_idempotency()
    test_process_elevenlabs_event_job_no_email()
    test_process_elevenlabs_event_job_no_studio_name()
    print("All worker tests passed.")
