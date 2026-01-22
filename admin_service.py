from datetime import datetime, timedelta
import os
import json
import csv
from io import StringIO
from typing import Optional
from sqlalchemy.orm import Session
from sqlalchemy import func
from models import User, Agent, Plan, Subscription, PhoneNumber, UsageEvent
from auth import hash_password, generate_random_password
from mailer import send_email
import audit_logger

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

    def reset_password_random(self, user_id: int, admin_username: str) -> str:
        """
        Resets a user's password to a random one.
        Returns the new plaintext password.
        """
        user = self.db.query(User).filter(User.id == user_id).first()
        if not user:
            raise ValueError("User not found")

        new_password = generate_random_password()
        user.password_hash = hash_password(new_password)
        self.db.commit()

        # Audit Log
        audit_logger.log_action(
            admin_username=admin_username,
            action="reset_password",
            target=f"user_id={user_id} ({user.username})",
            details="Password reset to random value"
        )

        # Email the user
        subject = f"Reset Password - {user.studio_name or user.username}"
        body = f"""
        <p>Ciao {user.username},</p>
        <p>La tua password è stata resettata dall'amministratore.</p>
        <p>Nuova password: <b>{new_password}</b></p>
        <p>Ti consigliamo di cambiarla al primo accesso.</p>
        """
        try:
            send_email(user.email, subject, body)
        except Exception as e:
            # We log the error but don't fail the transaction, as the PW is already changed.
            # However, the admin needs to know the PW to communicate it manually if email fails.
            print(f"Failed to send reset email: {e}")

        return new_password

    def export_minutes_csv(self, from_date: datetime, to_date: datetime) -> str:
        """
        Exports usage minutes (UsageEvents) to a CSV string.
        Cols: UserID, ClientName, AgentID, Date, CallDuration(s), CallID
        """
        events = self.db.query(UsageEvent).join(User).join(Agent).filter(
            UsageEvent.started_at >= from_date,
            UsageEvent.started_at <= to_date
        ).all()

        output = StringIO()
        writer = csv.writer(output)
        writer.writerow(["UserID", "ClientName", "AgentID", "Date", "DurationSec", "CallID"])

        for event in events:
            writer.writerow([
                event.user_id,
                event.user.studio_name or event.user.username,
                event.agent.agent_id,
                event.started_at.isoformat(),
                event.billed_seconds,
                event.call_id
            ])

        return output.getvalue()

    def export_logs_csv(self, from_date: datetime, to_date: datetime, client_filter: Optional[str] = None) -> str:
        """
        Exports logs from logs directory to a CSV string.
        Cols: Timestamp, AgentID, Caller, Status, Duration, Summary
        """
        output = StringIO()
        writer = csv.writer(output)
        writer.writerow(["Timestamp", "AgentID", "Caller", "Status", "Duration", "Summary"])

        logs_dir = "logs"
        if not os.path.exists(logs_dir):
            return output.getvalue()

        # Gather agent_ids to check
        agent_ids = []
        if client_filter:
            agent_ids = [client_filter]
        else:
            # List all .log files
            for filename in os.listdir(logs_dir):
                if filename.endswith(".log"):
                    agent_ids.append(filename[:-4])

        for agent_id in agent_ids:
            log_path = os.path.join(logs_dir, f"{agent_id}.log")
            if not os.path.exists(log_path):
                continue

            with open(log_path, "r", encoding="utf-8") as f:
                for line in f:
                    try:
                        entry = json.loads(line)
                        ts_str = entry.get("timestamp")
                        if not ts_str:
                            continue

                        ts_dt = datetime.fromisoformat(ts_str)
                        # Filter by date range
                        # We compare aware vs aware or naive vs naive.
                        # Usually from_date/to_date might be naive or aware depending on how they are constructed.
                        # Assuming they are naive UTC or similar, we should ensure compatibility.
                        # For simplicity, if ts_dt has timezone, remove it or compare properly.
                        # Let's strip timezone for comparison if inputs are naive
                        if from_date.tzinfo is None and ts_dt.tzinfo is not None:
                            ts_dt = ts_dt.replace(tzinfo=None)

                        if not (from_date <= ts_dt <= to_date):
                            continue

                        data = entry.get("data", {})

                        # Extract fields
                        caller = data.get("caller_number", "N/D")

                        # Status check
                        status = data.get("status", "success") # default success

                        duration = data.get("duration_secs", "")
                        summary = data.get("summary") or data.get("analysis", {}).get("summary", "")

                        writer.writerow([
                            ts_str,
                            agent_id,
                            caller,
                            status,
                            duration,
                            summary
                        ])
                    except (json.JSONDecodeError, ValueError):
                        continue

        return output.getvalue()
