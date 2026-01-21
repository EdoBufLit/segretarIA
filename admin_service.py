from datetime import datetime, timedelta, date
import os
import csv
import io
import json
from pathlib import Path
from typing import Optional
from sqlalchemy.orm import Session
from models import User, Agent, Plan, Subscription, PhoneNumber
from auth import hash_password
from mailer import send_email

LOGS_DIR = Path("logs")

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

    def toggle_user_active_status(self, user_id: int) -> User:
        user = self.db.query(User).filter(User.id == user_id).first()
        if not user:
            raise ValueError("User not found")

        user.is_active = not user.is_active
        self.db.commit()
        self.db.refresh(user)
        return user

    def export_logs_csv(self, date_from: Optional[date] = None, date_to: Optional[date] = None, agent_id: Optional[str] = None) -> str:
        output = io.StringIO()
        writer = csv.writer(output)

        # Header
        writer.writerow(["timestamp", "client", "durata", "categoria", "urgenza", "stato"])

        if not LOGS_DIR.exists():
            return output.getvalue()

        # Iterate over log files
        for log_file in LOGS_DIR.glob("*.log"):
            current_agent_id = log_file.stem

            # Filter by agent_id
            if agent_id and current_agent_id != agent_id:
                continue

            with log_file.open("r", encoding="utf-8") as f:
                for line in f:
                    try:
                        entry = json.loads(line)

                        # Date Filter
                        ts_str = entry.get("timestamp")
                        if not ts_str:
                            continue

                        try:
                            entry_date = datetime.fromisoformat(ts_str).date()
                        except ValueError:
                            continue

                        if date_from and entry_date < date_from:
                            continue
                        if date_to and entry_date > date_to:
                            continue

                        # Extract Data
                        data = entry.get("data", {})
                        analysis = data.get("analysis", {})

                        # CSV columns: timestamp, client, durata, categoria, urgenza, stato
                        row = [
                            ts_str,
                            entry.get("agent_id", current_agent_id),
                            data.get("duration_secs", ""),
                            analysis.get("matter_type", ""),
                            analysis.get("urgency", ""),
                            data.get("status", "")
                        ]
                        writer.writerow(row)
                    except json.JSONDecodeError:
                        continue

        return output.getvalue()
