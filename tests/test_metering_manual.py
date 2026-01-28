
import unittest
from unittest.mock import MagicMock, patch
from datetime import datetime, timedelta
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from db import Base
from models import Agent, User, UsageEvent, PhoneNumber, AgentRouting, Subscription, Plan, CallLog
from jobs.eleven_jobs import process_elevenlabs_event_job
import logging

# Mocks
MOCK_TRANSCRIPT_PAYLOAD = {
    "type": "post_call_transcription",
    "data": {
        "agent_id": "test_agent_id",
        "metadata": {
            # NO start_time_unix_secs
            # NO call_duration_secs
            "phone_call": {
                "call_sid": "test_call_id_transcript_fallback",
                "number": "+390000000000",
                "external_number": "+393331234567"
            }
        },
        "transcript": [
            {"role": "user", "message": "Ciao", "time_in_call_secs": 10},
            {"role": "agent", "message": "Buongiorno", "time_in_call_secs": 25}
        ]
    }
}

class TestMetering(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(self.engine)
        self.Session = sessionmaker(bind=self.engine)
        self.db = self.Session()

        # Setup Data
        plan = Plan(code="test_plan", minutes_per_cycle=1000)
        self.db.add(plan)
        user = User(username="testuser", email="test@example.com", password_hash="hash", role="client", is_active=True, studio_name="Test Studio")
        self.db.add(user)
        self.db.flush()

        sub = Subscription(
            user_id=user.id,
            plan_id=plan.id,
            state="active",
            cycle_start=datetime.utcnow(),
            cycle_end=datetime.utcnow() + timedelta(days=30)
        )
        self.db.add(sub)

        agent = Agent(agent_id="test_agent_id", display_name="Test Agent")
        self.db.add(agent)
        self.db.flush()

        routing = AgentRouting(user_id=user.id, agent_id="test_agent_id", status="active", is_active=True)
        self.db.add(routing)

        self.db.commit()

    def tearDown(self):
        self.db.close()

    @patch("jobs.eleven_jobs.SessionLocal")
    @patch("jobs.eleven_jobs.get_queue")
    @patch("jobs.eleven_jobs.summarize_call")
    @patch("jobs.eleven_jobs.logger")
    @patch("jobs.eleven_jobs.ensure_subscription_for_user")
    def test_transcript_fallback(self, mock_ensure, mock_logger, mock_summarize, mock_queue, MockSession):
        MockSession.return_value.__enter__.return_value = self.db
        MockSession.return_value.__exit__.return_value = None

        mock_summarize.return_value = {"summary": "foo"}

        # Execute
        process_elevenlabs_event_job(MOCK_TRANSCRIPT_PAYLOAD)

        # Verify UsageEvent
        call_log = self.db.query(CallLog).filter_by(agent_id="test_agent_id").first()
        self.assertIsNotNone(call_log)
        event = self.db.query(UsageEvent).filter_by(call_id=call_log.id).first()
        self.assertIsNotNone(event)
        self.assertEqual(event.billed_seconds, 25) # Max of 10 and 25

        # Verify Log
        # We check if specific log message was called
        log_calls = [call[0][0] for call in mock_logger.info.call_args_list]
        found_log = False
        for msg in log_calls:
            if "[USAGE] Inserted usage_event seconds=%s" in msg:
                found_log = True
                break
        self.assertTrue(found_log, "Usage log message not found")

if __name__ == "__main__":
    unittest.main()
