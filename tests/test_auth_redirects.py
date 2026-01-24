import os
import unittest
from unittest import mock
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

import app as app_module
import db as db_module
from db import Base, get_db
from models import User
from auth import hash_password

class AuthRedirectsTests(unittest.TestCase):
    def setUp(self) -> None:
        # Use file DB for debugging
        self.db_path = "test_auth.db"
        if os.path.exists(self.db_path):
            os.remove(self.db_path)

        self.engine = create_engine(
            f"sqlite:///{self.db_path}",
            connect_args={"check_same_thread": False},
        )
        self.SessionLocal = sessionmaker(
            autocommit=False,
            autoflush=False,
            bind=self.engine,
        )

        # Ensure models are loaded
        import models

        Base.metadata.create_all(bind=self.engine)

        self._original_db_session = db_module.SessionLocal
        db_module.SessionLocal = self.SessionLocal

        def override_get_db():
            db = self.SessionLocal()
            try:
                yield db
            finally:
                db.close()

        app_module.app.dependency_overrides[get_db] = override_get_db

        self._original_startup = list(app_module.app.router.on_startup)
        app_module.app.router.on_startup = []

        self.client = TestClient(app_module.app)

        # Create seed users
        self.create_users()

    def create_users(self):
        session = self.SessionLocal()
        try:
            admin = User(
                username="admin",
                email="admin@example.com",
                password_hash=hash_password("password"),
                role="admin",
                is_active=True
            )
            client = User(
                username="client",
                email="client@example.com",
                password_hash=hash_password("password"),
                role="client",
                is_active=True
            )
            session.add(admin)
            session.add(client)
            session.commit()
            self.admin_id = admin.id
            self.client_id = client.id
        finally:
            session.close()

    def tearDown(self) -> None:
        app_module.app.dependency_overrides.clear()
        app_module.app.router.on_startup = self._original_startup
        db_module.SessionLocal = self._original_db_session
        self.engine.dispose()
        if os.path.exists(self.db_path):
            os.remove(self.db_path)

    def login_as(self, username):
        response = self.client.post("/login", data={"username": username, "password": "password"}, follow_redirects=False)
        return response

    def test_unauthenticated_dashboard_redirects_to_login(self):
        response = self.client.get("/dashboard", follow_redirects=False)
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.headers["location"], "/login")

    def test_unauthenticated_client_dashboard_redirects_to_dashboard(self):
        # /client/dashboard -> /dashboard -> /login
        response = self.client.get("/client/dashboard", follow_redirects=False)
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.headers["location"], "/dashboard")

    def test_admin_can_access_dashboard(self):
        self.login_as("admin")
        response = self.client.get("/dashboard", follow_redirects=False)
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"Segreteria", response.content)

    def test_client_can_access_dashboard(self):
        self.login_as("client")
        response = self.client.get("/dashboard", follow_redirects=False)
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"Segreteria", response.content)

    def test_client_accessing_client_dashboard_redirects_to_dashboard(self):
        self.login_as("client")
        response = self.client.get("/client/dashboard", follow_redirects=False)
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.headers["location"], "/dashboard")

    def test_admin_accessing_client_dashboard_redirects_to_dashboard(self):
        self.login_as("admin")
        response = self.client.get("/client/dashboard", follow_redirects=False)
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.headers["location"], "/dashboard")

    def test_api_access_unauthenticated_returns_json_error(self):
        # Verify API returns JSON error (401)
        response = self.client.get("/me", follow_redirects=False)
        self.assertEqual(response.status_code, 401)
        try:
            data = response.json()
            self.assertIn("detail", data)
            self.assertEqual(data["detail"], "Not authenticated")
        except:
            self.fail("API response should be JSON")

if __name__ == "__main__":
    unittest.main()
