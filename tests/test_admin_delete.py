import os
import tempfile
import unittest
from unittest import mock
import datetime

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

os.environ.setdefault("OPENAI_API_KEY", "test-key")

import admin_seed
import app as app_module
import db as db_module
from admin_seed import ensure_default_admin
from db import Base, get_db
from models import User, Subscription, Plan, UsageEvent, PhoneNumber, Agent, AgentRouting, CallLog
from auth import hash_password

class AdminDeleteTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = os.path.join(self.temp_dir.name, "test.db")
        self.engine = create_engine(
            f"sqlite:///{self.db_path}",
            connect_args={"check_same_thread": False},
        )
        self.SessionLocal = sessionmaker(
            autocommit=False,
            autoflush=False,
            bind=self.engine,
        )
        Base.metadata.create_all(bind=self.engine)

        self._original_admin_seed_session = admin_seed.SessionLocal
        self._original_db_session = db_module.SessionLocal
        admin_seed.SessionLocal = self.SessionLocal
        db_module.SessionLocal = self.SessionLocal

        def override_get_db():
            db = self.SessionLocal()
            try:
                yield db
            finally:
                db.close()

        self._original_startup = list(app_module.app.router.on_startup)
        app_module.app.router.on_startup = []
        app_module.app.dependency_overrides[get_db] = override_get_db
        self.client = TestClient(app_module.app)

        # Create Admin
        session = self.SessionLocal()
        admin = User(
            username="admin",
            email="admin@example.com",
            password_hash=hash_password("adminpass"),
            role="admin",
            is_active=True
        )
        session.add(admin)
        session.commit()
        session.close()

    def tearDown(self) -> None:
        app_module.app.dependency_overrides.clear()
        app_module.app.router.on_startup = self._original_startup
        admin_seed.SessionLocal = self._original_admin_seed_session
        db_module.SessionLocal = self._original_db_session
        Base.metadata.drop_all(bind=self.engine)
        self.engine.dispose()
        self.temp_dir.cleanup()

    def login_admin(self):
        return self.client.post("/login", data={"username": "admin", "password": "adminpass"})

    def test_delete_client_user(self):
        self.login_admin()

        # Create client
        session = self.SessionLocal()
        client = User(
            username="client",
            email="client@example.com",
            password_hash=hash_password("clientpass"),
            role="client",
            is_active=True
        )
        session.add(client)
        session.commit()
        client_id = client.id
        session.close()

        # Verify exists
        res = self.client.get("/admin/users")
        self.assertEqual(res.status_code, 200)
        self.assertTrue(any(u["id"] == client_id for u in res.json()["items"]))

        # Delete
        res = self.client.delete(f"/admin/users/{client_id}")
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.json()["status"], "ok")

        # Verify gone
        session = self.SessionLocal()
        u = session.query(User).filter_by(id=client_id).first()
        self.assertIsNone(u)
        session.close()

    def test_delete_client_with_agent_routing(self):
        self.login_admin()

        session = self.SessionLocal()

        client = User(
            username="client_routing",
            email="client_routing@example.com",
            password_hash=hash_password("pass"),
            role="client",
            is_active=True
        )
        session.add(client)
        session.commit()

        # Add Phone Number
        ph = PhoneNumber(
            e164="+39000000001",
            user_id=client.id,
            provider="test",
            status="active"
        )
        session.add(ph)
        session.commit()

        # Add AgentRouting
        routing = AgentRouting(
            user_id=client.id,
            agent_id="ag_routing",
            phone_number_id=ph.id,
            is_active=True
        )
        session.add(routing)
        session.commit()

        client_id = client.id
        routing_id = routing.id
        session.close()

        # Delete
        res = self.client.delete(f"/admin/users/{client_id}")
        self.assertEqual(res.status_code, 200)

        # Verify
        session = self.SessionLocal()
        self.assertIsNone(session.query(User).filter_by(id=client_id).first())
        self.assertIsNone(session.query(PhoneNumber).filter_by(user_id=client_id).first())
        self.assertIsNone(session.query(AgentRouting).filter_by(id=routing_id).first())
        session.close()

    def test_delete_client_with_dependencies(self):
        self.login_admin()

        session = self.SessionLocal()

        # Plan needed for subscription
        plan = Plan(code="starter", minutes_per_cycle=100)
        session.add(plan)
        session.commit()

        client = User(
            username="client_dep",
            email="client_dep@example.com",
            password_hash=hash_password("pass"),
            role="client",
            is_active=True
        )
        session.add(client)
        session.commit()

        # Add subscription
        sub = Subscription(
            user_id=client.id,
            plan_id=plan.id,
            state="active",
            cycle_start=datetime.datetime.utcnow(),
            cycle_end=datetime.datetime.utcnow()
        )
        session.add(sub)
        session.commit()

        # Add Phone Number
        ph = PhoneNumber(
            e164="+39000000000",
            user_id=client.id,
            provider="test",
            status="active"
        )
        session.add(ph)
        session.commit()

        # Add Usage Event
        # Need Agent first
        agent = Agent(agent_id="ag1", display_name="Agent 1")
        session.add(agent)
        session.commit()

        call_log = CallLog(
            agent_id=agent.agent_id,
            user_id=client.id,
            timestamp=datetime.datetime.utcnow(),
            text="Test call",
            status="success",
            raw_data={"data": {"call_id": "test_call_id"}},
        )
        session.add(call_log)
        session.flush()

        evt = UsageEvent(
            subscription_id=sub.id,
            user_id=client.id,
            agent_id=agent.id,
            call_log_id=call_log.id,
            started_at=datetime.datetime.utcnow(),
            ended_at=datetime.datetime.utcnow(),
            billed_seconds=60
        )
        session.add(evt)
        session.commit()

        client_id = client.id
        session.close()

        # Delete
        res = self.client.delete(f"/admin/users/{client_id}")
        self.assertEqual(res.status_code, 200)

        # Verify
        session = self.SessionLocal()
        self.assertIsNone(session.query(User).filter_by(id=client_id).first())
        self.assertEqual(session.query(Subscription).filter_by(user_id=client_id).count(), 0)
        self.assertEqual(session.query(PhoneNumber).filter_by(user_id=client_id).count(), 0)
        self.assertEqual(session.query(UsageEvent).filter_by(user_id=client_id).count(), 0)
        # Agent should remain
        self.assertIsNotNone(session.query(Agent).filter_by(agent_id="ag1").first())
        session.close()

    def test_cannot_delete_self(self):
        self.login_admin()

        session = self.SessionLocal()
        admin = session.query(User).filter_by(username="admin").first()
        admin_id = admin.id
        session.close()

        res = self.client.delete(f"/admin/users/{admin_id}")
        self.assertEqual(res.status_code, 403)
        self.assertIn("self", res.json()["detail"])

    def test_cannot_delete_other_admin(self):
        self.login_admin()

        session = self.SessionLocal()
        other_admin = User(
            username="admin2",
            email="admin2@example.com",
            password_hash=hash_password("pass"),
            role="admin",
            is_active=True
        )
        session.add(other_admin)
        session.commit()
        other_id = other_admin.id
        session.close()

        res = self.client.delete(f"/admin/users/{other_id}")
        self.assertEqual(res.status_code, 403)
        self.assertIn("other admins", res.json()["detail"])

if __name__ == "__main__":
    unittest.main()
