import os
import tempfile
import unittest
from unittest import mock

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

os.environ.setdefault("OPENAI_API_KEY", "test-key")

import admin_seed
import app as app_module
import db as db_module
from admin_seed import ensure_default_admin
from db import Base, get_db
from models import User


class AuthFlowsTests(unittest.TestCase):
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

    def tearDown(self) -> None:
        app_module.app.dependency_overrides.clear()
        app_module.app.router.on_startup = self._original_startup
        admin_seed.SessionLocal = self._original_admin_seed_session
        db_module.SessionLocal = self._original_db_session
        Base.metadata.drop_all(bind=self.engine)
        self.engine.dispose()
        self.temp_dir.cleanup()

    def test_ensure_default_admin_is_idempotent(self) -> None:
        with mock.patch.dict(
            os.environ,
            {
                "ADMIN_USERNAME": "seed_admin",
                "ADMIN_PASSWORD": "password123",
                "ADMIN_EMAIL": "seed_admin@example.com",
            },
        ):
            ensure_default_admin()
            ensure_default_admin()

        session = self.SessionLocal()
        try:
            admins = (
                session.query(User)
                .filter(User.username == "seed_admin", User.role == "admin")
                .all()
            )
            self.assertEqual(len(admins), 1)
        finally:
            session.close()

    def test_register_creates_client_user(self) -> None:
        response = self.client.post(
            "/register",
            data={
                "username": "client_user",
                "email": "client@example.com",
                "password": "password123",
                "password_confirm": "password123",
            },
            follow_redirects=False,
        )
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.headers["location"], "/login?registered=1")

        session = self.SessionLocal()
        try:
            user = session.query(User).filter(User.username == "client_user").first()
            self.assertIsNotNone(user)
            self.assertEqual(user.role, "client")
            self.assertTrue(user.is_active)
        finally:
            session.close()

    def test_register_duplicate_username_or_email_shows_error(self) -> None:
        session = self.SessionLocal()
        try:
            session.add(
                User(
                    username="existing_user",
                    email="existing@example.com",
                    password_hash="hashed",
                    role="client",
                    is_active=True,
                )
            )
            session.commit()
        finally:
            session.close()

        response = self.client.post(
            "/register",
            data={
                "username": "existing_user",
                "email": "existing@example.com",
                "password": "password123",
                "password_confirm": "password123",
            },
        )
        self.assertEqual(response.status_code, 200)
        self.assertIn("già in uso", response.text)


if __name__ == "__main__":
    unittest.main()
