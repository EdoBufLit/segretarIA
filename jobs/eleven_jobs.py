import json
import logging
from typing import Dict, Any, Optional
from datetime import datetime, timedelta
from db import SessionLocal
from models import Agent, User, UsageEvent, PhoneNumber, AgentRouting, UnassignedEvent, Subscription
from billing_service import BillingService
from jobs.email_jobs import send_email_job
from call_utils import log_call, summarize_call, build_email_body_html, extract_transcript_text
from queue_utils import get_queue
import os

logger = logging.getLogger("eleven_jobs")
STUDIO_NAME = os.getenv("STUDIO_NAME", "Segreteria IA")

def process_elevenlabs_event_job(payload: dict):
    """
    Async job to process ElevenLabs webhook event:
    - Upserts PhoneNumber/AgentRouting
    - Checks User/Subscription status
    - Idempotency check
    - Log call to file
    - Meter usage
    - Enqueue email
    """
    logger.info("Processing ElevenLabs event...")

    data = payload.get("data", {})
    agent_id = data.get("agent_id")

    # We expect the payload to be already validated as 'post_call_transcription' by the endpoint.

    if not agent_id:
        logger.error("No agent_id in payload")
        return

    # Extract metadata
    metadata = data.get("metadata", {})
    start_unix = metadata.get("start_time_unix_secs")
    duration_secs = metadata.get("call_duration_secs")

    # Inbound Number (to_number)
    phone_call_meta = metadata.get("phone_call", {})
    to_number = phone_call_meta.get("number") or phone_call_meta.get("to_number")

    # Caller Number (from_number)
    caller_number = (
        phone_call_meta.get("external_number")
        or metadata.get("from_number")
        or metadata.get("caller_number")
        or metadata.get("phone_number")
        or "N/D"
    )

    call_id = phone_call_meta.get("call_sid") or data.get("conversation_id")

    # === DB OPERATIONS (SYNC & VALIDATION) ===
    with SessionLocal() as db:
        try:
            # 1. Upsert PhoneNumber
            phone_obj = None
            if to_number:
                if not to_number.startswith("+"):
                    to_number = "+" + to_number

                phone_obj = db.query(PhoneNumber).filter(PhoneNumber.e164 == to_number).first()
                if not phone_obj:
                    logger.info(f"[JOB] Discovered new phone number {to_number}")
                    phone_obj = PhoneNumber(
                        e164=to_number,
                        provider="elevenlabs",
                        status="active",
                        user_id=None
                    )
                    db.add(phone_obj)
                    db.flush()

            # 2. Upsert AgentRouting
            routing = db.query(AgentRouting).filter(AgentRouting.agent_id == agent_id).first()
            if routing:
                routing.last_event_at = datetime.utcnow()
                if not routing.phone_number_id and phone_obj:
                    routing.phone_number_id = phone_obj.id
            else:
                logger.info(f"[JOB] Discovered new unassigned agent {agent_id}")
                routing = AgentRouting(
                    agent_id=agent_id,
                    user_id=None,
                    status="unassigned",
                    phone_number_id=phone_obj.id if phone_obj else None,
                    last_event_at=datetime.utcnow()
                )
                db.add(routing)
            db.commit()

            # 3. Validation: Agent & User
            agent_obj = db.query(Agent).filter_by(agent_id=agent_id).first()
            user = None
            if agent_obj:
                user = db.query(User).filter(User.agents.contains(agent_obj)).first()

            if not agent_obj or not user:
                logger.warning(f"[JOB] Unassigned agent/user for agent_id {agent_id}. Storing UnassignedEvent.")
                unassigned = UnassignedEvent(
                    agent_id=agent_id,
                    phone_number=to_number,
                    payload=payload
                )
                db.add(unassigned)
                db.commit()
                return # Stop processing

            # 4. Check Suspension
            if not user.is_active:
                logger.warning(f"[JOB] Suspended user {user.username}. Blocking.")
                return

            active_sub = db.query(Subscription).filter(
                Subscription.user_id == user.id,
                Subscription.state == "active"
            ).first()

            if not active_sub:
                logger.warning(f"[JOB] No active subscription for user {user.username}. Blocking.")
                return

            # 5. Idempotency
            if call_id:
                exists = db.query(UsageEvent).filter_by(call_id=call_id).first()
                if exists:
                    logger.info(f"[JOB] Duplicate call_id {call_id}. Skipping.")
                    return

        except Exception as e:
            logger.error(f"[JOB] DB Error: {e}")
            # We treat DB errors as fatal for processing to avoid incorrect billing/logging
            return

    # === LOGIC PROCESSING ===
    started_at = None
    ended_at = None
    if isinstance(start_unix, (int, float)):
        started_dt = datetime.utcfromtimestamp(start_unix)
        started_at = started_dt.isoformat()
        if isinstance(duration_secs, (int, float)):
            ended_dt = datetime.utcfromtimestamp(start_unix + duration_secs)
            ended_at = ended_dt.isoformat()

    # Extract transcript text
    transcript_text = extract_transcript_text(payload)

    # Analysis from ElevenLabs
    analysis_obj: Dict[str, Any] = data.get("analysis", {}) or {}
    el_summary: Optional[str] = analysis_obj.get("transcript_summary")

    # OpenAI Summarization
    try:
        analysis_structured = summarize_call(transcript_text, el_summary)
    except Exception as e:
        logger.warning(f"[OPENAI] Error in summarize_call: {e}")
        analysis_structured = {
            "summary": transcript_text,
            "client_name": None
        }

    # Status
    status = "success"
    if duration_secs and duration_secs < 3:
        status = "failure"

    # LOG CALL (File)
    log_call(agent_id, {
        "transcript_text": transcript_text,
        "analysis": analysis_structured,
        "caller_number": caller_number,
        "call_id": call_id,
        "started_at": started_at,
        "ended_at": ended_at,
        "duration_secs": duration_secs,
        "status": status,
        "summary": analysis_structured.get("summary")
    })

    # METERING (DB)
    if duration_secs and agent_id and call_id:
        try:
            with SessionLocal() as db:
                billing_service = BillingService(db)
                billing_service.meter_call(
                    agent_id=agent_id,
                    duration_secs=int(duration_secs),
                    call_id=call_id,
                    started_at=datetime.fromisoformat(started_at) if started_at else datetime.utcnow() - timedelta(seconds=duration_secs),
                    ended_at=datetime.fromisoformat(ended_at) if ended_at else datetime.utcnow()
                )
        except Exception as e:
            logger.error(f"Metering failed: {e}")

    # ENQUEUE EMAIL
    clients_file = os.getenv("CLIENTS_FILE", "clients.json")
    studio_name = STUDIO_NAME
    email_to = os.getenv("EMAIL_TO")

    if os.path.exists(clients_file):
        try:
            with open(clients_file, "r") as f:
                clients_data = json.load(f)
                if agent_id in clients_data:
                    cfg = clients_data[agent_id]
                    studio_name = cfg.get("studio_name", studio_name)
                    email_to = cfg.get("email_to", email_to)
        except Exception as e:
            logger.error(f"Error loading clients.json: {e}")

    if not email_to:
        logger.error("No email_to configured, skipping email.")
        return

    try:
        email_body = build_email_body_html(
            transcript_text=transcript_text,
            analysis=analysis_structured,
            caller_number=caller_number,
            started_at=started_at,
            ended_at=ended_at,
            raw_payload=payload,
            studio_name=studio_name,
            agency_name=STUDIO_NAME,
        )

        subject = f"[Segreteria IA] Nuova chiamata per {studio_name} da {caller_number}"

        queue = get_queue()
        queue.enqueue(send_email_job, email_to, subject, email_body)
        logger.info(f"Email job enqueued for {email_to}")

    except Exception as e:
        logger.error(f"Error preparing/enqueuing email: {e}")
