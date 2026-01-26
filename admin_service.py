from datetime import datetime, timedelta
import os
import csv
import json
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

    def get_all_phone_numbers(self):
        return self.db.query(PhoneNumber).all()

    def create_phone_number(self, e164: str, user_id: int):
        user = self.db.query(User).filter_by(id=user_id).first()
        if not user:
            raise ValueError("User not found")

        new_phone = PhoneNumber(
            e164=e164,
            user_id=user_id,
            status="active",
            released_at=None
        )
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
        phone.user_id = None
        self.db.commit()
        return phone

    def reactivate_phone_number(self, phone_id: int, user_id: int, admin_username: str):
        """
        Reactivates a released phone number and assigns it to a user.
        """
        phone = self.db.query(PhoneNumber).filter_by(id=phone_id).first()
        if not phone:
            raise ValueError("Phone number not found")

        if not phone.released_at:
            raise ValueError("Phone number is not released")

        user = self.db.query(User).filter_by(id=user_id).first()
        if not user:
            raise ValueError("User not found")

        phone.status = "active"
        phone.released_at = None
        phone.user_id = user.id
        self.db.commit()

        # Audit Log
        audit_logger.log_audit_event(
            db=self.db,
            actor_type="admin",
            action="reactivate_phone_number",
            entity_type="phone_number",
            entity_id=str(phone_id),
            meta={"e164": phone.e164, "new_user_id": user_id},
            admin_username=admin_username,
            target_str=f"e164={phone.e164} user={user.username}"
        )
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

    def delete_phone_number_permanent(self, phone_id: int, admin_username: str):
        """
        Hard delete of a phone number from the database.
        Irreversible action.
        """
        phone = self.db.query(PhoneNumber).filter_by(id=phone_id).first()
        if not phone:
            raise ValueError("Phone number not found")

        e164 = phone.e164
        self.db.delete(phone)
        self.db.commit()

        # Audit Log
        audit_logger.log_audit_event(
            db=self.db,
            actor_type="admin",
            action="delete_phone_number_permanent",
            entity_type="phone_number",
            entity_id=str(phone_id),
            meta={"e164": e164, "admin_username": admin_username},
            admin_username=admin_username,
            target_str=f"e164={e164}"
        )
        return True

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

        # Audit Log (DB + File)
        audit_logger.log_audit_event(
            db=self.db,
            actor_type="admin",
            action="reset_password",
            entity_type="user",
            entity_id=str(user.id),
            meta={"admin_username": admin_username},
            admin_username=admin_username,
            target_str=f"user_id={user_id} ({user.username})"
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

    def export_minutes_csv_generator(self, from_date: datetime, to_date: datetime, admin_username: str = "system"):
        """
        Exports usage minutes (UsageEvents) as a CSV generator.
        Cols: UserID, ClientName, AgentID, Date, CallDuration(s), CallID
        """

        # Audit Log (DB + File)
        audit_logger.log_audit_event(
            db=self.db,
            actor_type="admin",
            action="export_minutes",
            meta={"from_date": str(from_date), "to_date": str(to_date)},
            admin_username=admin_username,
            target_str=f"range={from_date}..{to_date}"
        )

        # Yield header
        output = StringIO()
        writer = csv.writer(output)
        writer.writerow(["UserID", "ClientName", "AgentID", "Date", "DurationSec", "CallID"])
        yield output.getvalue()
        output.seek(0)
        output.truncate(0)

        # Batch query to avoid OOM
        batch_size = 1000
        offset = 0
        while True:
            events = self.db.query(UsageEvent).join(User).join(Agent).filter(
                UsageEvent.started_at >= from_date,
                UsageEvent.started_at <= to_date
            ).order_by(UsageEvent.id).offset(offset).limit(batch_size).all()

            if not events:
                break

            for event in events:
                writer.writerow([
                    event.user_id,
                    event.user.studio_name or event.user.username,
                    event.agent.agent_id,
                    event.started_at.isoformat(),
                    event.billed_seconds,
                    event.call_id
                ])
                yield output.getvalue()
                output.seek(0)
                output.truncate(0)

            offset += batch_size

    def export_logs_csv_generator(self, from_date: datetime, to_date: datetime, client_filter: Optional[str] = None, admin_username: str = "system"):
        """
        Exports logs from DB (CallLog) as a CSV generator.
        Cols: Timestamp, AgentID, Caller, Status, Duration, Summary
        """

        # Audit Log (DB + File)
        audit_logger.log_audit_event(
            db=self.db,
            actor_type="admin",
            action="export_logs",
            meta={"from_date": str(from_date), "to_date": str(to_date), "client_filter": client_filter},
            admin_username=admin_username,
            target_str=f"range={from_date}..{to_date} client={client_filter}"
        )

        output = StringIO()
        writer = csv.writer(output)
        writer.writerow(["Timestamp", "AgentID", "Caller", "Status", "Duration", "Summary", "Transcript", "AI_Analysis"])
        yield output.getvalue()
        output.seek(0)
        output.truncate(0)

        from models import CallLog

        query = self.db.query(CallLog).filter(
            CallLog.timestamp >= from_date,
            CallLog.timestamp <= to_date
        )

        if client_filter:
            # Check if client_filter is a User ID (integer)
            try:
                user_id = int(client_filter)
                # Find all agents for this user
                user = self.db.query(User).filter(User.id == user_id).first()
                if user:
                    agent_ids = [agent.agent_id for agent in user.agents]
                    query = query.filter(CallLog.agent_id.in_(agent_ids))
                else:
                    return # No user found, empty result
            except ValueError:
                # Assume it's an agent_id directly
                if client_filter.replace("-", "").replace("_", "").isalnum():
                     query = query.filter(CallLog.agent_id == client_filter)
                else:
                     return

        query = query.order_by(CallLog.timestamp.desc())

        # Batch query
        batch_size = 1000
        offset = 0
        while True:
            logs = query.offset(offset).limit(batch_size).all()
            if not logs:
                break

            for log in logs:
                ts_str = log.timestamp.isoformat() if log.timestamp else ""

                raw = log.raw_data or {}
                data = raw.get("data", {})

                caller = data.get("caller_number", "N/D")
                # Fallback to DB status if not in JSON, or vice versa
                status = log.status or data.get("status", "success")
                duration = data.get("duration_secs", "")

                # Analysis/Summary extraction
                analysis = data.get("analysis", {})
                summary = log.text or data.get("summary") or analysis.get("summary", "")

                transcript = data.get("transcript_text", "")
                analysis_json = json.dumps(analysis, ensure_ascii=False) if analysis else ""

                writer.writerow([
                    ts_str,
                    log.agent_id,
                    caller,
                    status,
                    duration,
                    summary,
                    transcript,
                    analysis_json
                ])
                yield output.getvalue()
                output.seek(0)
                output.truncate(0)

            offset += batch_size
