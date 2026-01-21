from datetime import datetime, timedelta
import os
from sqlalchemy.orm import Session
from models import User, Agent, Plan, Subscription, PhoneNumber
from auth import hash_password, generate_random_password
from mailer import send_email
from audit_logger import log_admin_action
import csv
import io

class AdminService:
    def __init__(self, db: Session, current_admin_username: str = "system"):
        self.db = db
        self.admin_username = current_admin_username
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

        phone_number = self.db.query(PhoneNumber).filter_by(user_id=user_id, status="pending_deprovision").first()
        if phone_number and phone_number.deprovision_at > datetime.utcnow():
            phone_number.status = "active"
            phone_number.deprovision_at = None
            phone_number.notified_at = None
            self.db.commit()

            admin_email = os.getenv("ADMIN_EMAIL", "admin@example.com")
            subject = f"[REACTIVATE] Disdetta numero annullata per {phone_number.e164}"
            body = f"<p>La disdetta del numero <b>{phone_number.e164}</b> per il cliente {client.studio_name or client.username} è stata annullata a seguito della riattivazione della sottoscrizione.</p>"
            send_email(admin_email, subject, body)

        return subscription

    def sync_clients_to_json(self):
        import json

        clients_json_path = "clients.json"

        try:
            with open(clients_json_path, "r") as f:
                clients_data = json.load(f)
        except (FileNotFoundError, json.JSONDecodeError):
            clients_data = {}

        updated_count = 0
        created_count = 0

        client_users = self.db.query(User).filter(User.role == "client").all()

        for user in client_users:
            for agent in user.agents:
                agent_id_str = str(agent.agent_id)
                if agent_id_str not in clients_data:
                    created_count += 1
                else:
                    updated_count += 1

                clients_data[agent_id_str] = {
                    **clients_data.get(agent_id_str, {}),
                    "studio_name": user.studio_name,
                    "email_to": user.email
                }

        with open(clients_json_path, "w") as f:
            json.dump(clients_data, f, indent=2, ensure_ascii=False)

        return {"created": created_count, "updated": updated_count}

    def get_all_phone_numbers(self):
        return self.db.query(PhoneNumber).all()

    def create_phone_number(self, e164: str, user_id: int):
        user = self.db.query(User).filter_by(id=user_id).first()
        if not user:
            raise ValueError("User not found")

        new_phone = PhoneNumber(e164=e164, user_id=user_id)
        self.db.add(new_phone)
        self.db.commit()
        self.db.refresh(new_phone)
        return new_phone

    def mark_phone_number_released(self, phone_id: int):
        phone = self.db.query(PhoneNumber).filter_by(id=phone_id).first()
        if not phone:
            raise ValueError("Phone number not found")

        phone.status = "released"
        phone.released_at = datetime.utcnow()
        self.db.commit()
        return phone

    def cancel_phone_number_deprovisioning(self, phone_id: int):
        phone = self.db.query(PhoneNumber).filter_by(id=phone_id).first()
        if not phone:
            raise ValueError("Phone number not found")

        if phone.status == "pending_deprovision":
            phone.status = "active"
            phone.deprovision_at = None
            phone.notified_at = None
            self.db.commit()

            admin_email = os.getenv("ADMIN_EMAIL", "admin@example.com")
            subject = f"[REACTIVATE] Disdetta numero annullata per {phone.e164}"
            body = f"<p>La disdetta del numero <b>{phone.e164}</b> è stata annullata manualmente dall'amministratore.</p>"
            send_email(admin_email, subject, body)

        return phone

    def suspend_client(self, user_id: int):
        user = self.db.query(User).filter(User.id == user_id, User.role == "client").first()
        if not user:
            raise ValueError("Client not found")

        user.is_active = False
        self.db.commit()

        log_admin_action(self.admin_username, f"Suspended user {user.username} (ID: {user_id})")
        return user

    def reset_password(self, user_id: int, new_password: str):
        user = self.db.query(User).filter(User.id == user_id).first()
        if not user:
            raise ValueError("User not found")

        user.password_hash = hash_password(new_password)
        self.db.commit()

        log_admin_action(self.admin_username, f"Reset password for user {user.username} (ID: {user_id})")
        return user

    def reset_password_random(self, user_id: int) -> User:
        user = self.db.query(User).filter(User.id == user_id).first()
        if not user:
            raise ValueError("User not found")

        new_password = generate_random_password()
        user.password_hash = hash_password(new_password)
        self.db.commit()

        # Send email with new password
        subject = "Your password has been reset"
        body = (
            f"<p>Hello {user.username},</p>"
            f"<p>Your password has been reset by an administrator.</p>"
            f"<p>New Password: <b>{new_password}</b></p>"
            f"<p>We strongly suggest you change this password after logging in.</p>"
        )
        send_email(user.email, subject, body)

        log_admin_action(self.admin_username, f"Reset password (random) for user {user.username} (ID: {user_id})")
        return user

    def export_clients_csv(self) -> str:
        clients = self.get_clients()
        output = io.StringIO()
        writer = csv.writer(output)

        headers = ["id", "username", "email", "studio_name", "is_active", "created_at"]
        writer.writerow(headers)

        for client in clients:
            writer.writerow([
                client.id,
                client.username,
                client.email,
                client.studio_name,
                client.is_active,
                client.created_at
            ])

        log_admin_action(self.admin_username, "Exported clients CSV")
        return output.getvalue()
