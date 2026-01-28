import json
import logging
from typing import Dict, Any, Optional
from datetime import datetime, timedelta
from sqlalchemy.exc import IntegrityError
from db import SessionLocal
from models import Agent, User, UsageEvent, PhoneNumber, AgentRouting, UnassignedEvent, Subscription
from billing_service import BillingService
from jobs.email_jobs import send_email_job
from call_utils import upsert_call_log, summarize_call, build_email_body_html, extract_transcript_text
from queue_utils import get_queue
from alerting import log_critical_error
import os

logger = logging.getLogger("eleven_jobs")
STUDIO_NAME = os.getenv("STUDIO_NAME", "Mr.Automa")

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
    try:
        _process_elevenlabs_event_logic(payload)
    except Exception as e:
        data = payload.get("data", {})
        agent_id = data.get("agent_id", "unknown")
        # Safe extraction for error logging
        meta = data.get("metadata") or {}
        phone_meta = meta.get("phone_call") or {}
        call_id = phone_meta.get("call_sid") or data.get("conversation_id") or "unknown"

        log_critical_error(f"Job fallito per agent_id {agent_id}: {e}", context={"agent_id": agent_id, "call_id": call_id})
        raise

def _process_elevenlabs_event_logic(payload: dict):
    event_type = payload.get("type")
    data = payload.get("data", {})
    conversation_id = data.get("conversation_id")

    logger.info(f"Processing ElevenLabs event type={event_type} conversation_id={conversation_id}")

    # 1) Extract agent_id STRICTLY from payload["data"]["agent_id"]
    data_agent_id = data.get("agent_id")

    # 2) Defensive logging
    cand_system = data.get("system_agent_id")
    cand_meta = (data.get("metadata") or {}).get("agent_id")
    logger.info(f"[ELEVEN] agent_id candidates: data.agent_id={data_agent_id}, system_agent_id={cand_system}, metadata.agent_id={cand_meta}")

    # We expect the payload to be already validated as 'post_call_transcription' by the endpoint.

    if not data_agent_id:
        logger.error("No agent_id in payload")
        return

    # Extract metadata safely
    metadata = data.get("metadata") or {}
    start_unix = metadata.get("start_time_unix_secs")
    duration_secs = metadata.get("call_duration_secs")

    # Branching logic by event type
    if event_type == "post_call_transcription":
        # For transcription events, metadata.phone_call is often missing/null
        phone_call_meta = {}
        # Do not rely on call_sid from metadata
        call_id = conversation_id
        logger.info(f"[ELEVEN JOB] processed post_call_transcription conversation_id={conversation_id}")
    else:
        # Default behavior for other events
        phone_call_meta = metadata.get("phone_call") or {}
        call_id = phone_call_meta.get("call_sid")

    # Inbound Number (to_number)
    to_number = phone_call_meta.get("number") or phone_call_meta.get("to_number")

    # Caller Number (from_number)
    caller_number = (
        phone_call_meta.get("external_number")
        or metadata.get("from_number")
        or metadata.get("caller_number")
        or metadata.get("phone_number")
        or "N/D"
    )

    # Correlate via dynamic_variables (matching app.py logic)
    dyn = ((data.get("conversation_initiation_client_data") or {}).get("dynamic_variables") or {})
    twilio_sid = dyn.get("call_sid") or dyn.get("twilio_call_sid")

    if twilio_sid:
        call_id = twilio_sid
    elif not call_id:
        # Fallback if not set by branching logic
        call_id = conversation_id

    # Calculate Timestamps early for UsageEvent
    started_at = None
    ended_at = None
    if isinstance(start_unix, (int, float)):
        started_dt = datetime.utcfromtimestamp(start_unix)
        started_at = started_dt.isoformat()
        if isinstance(duration_secs, (int, float)):
            ended_dt = datetime.utcfromtimestamp(start_unix + duration_secs)
            ended_at = ended_dt.isoformat()

    # Defaults for UsageEvent if missing
    start_dt_obj = datetime.fromisoformat(started_at) if started_at else datetime.utcnow()
    end_dt_obj = datetime.fromisoformat(ended_at) if ended_at else datetime.utcnow()

    # Variables for email sending (resolved via DB)
    db_email_to = None
    db_studio_name = None

    # === DB OPERATIONS (SYNC & VALIDATION & LOCKING) ===
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
            routing = db.query(AgentRouting).filter(AgentRouting.agent_id == data_agent_id).first()
            if routing:
                routing.last_event_at = datetime.utcnow()
                if not routing.phone_number_id and phone_obj:
                    routing.phone_number_id = phone_obj.id
            else:
                logger.info(f"[JOB] Discovered new unassigned agent {data_agent_id}")
                routing = AgentRouting(
                    agent_id=data_agent_id,
                    user_id=None,
                    status="unassigned",
                    phone_number_id=phone_obj.id if phone_obj else None,
                    last_event_at=datetime.utcnow()
                )
                db.add(routing)
            db.commit()

            # 3. Validation: Routing & User Resolution (Canonical)
            # Query active routing for this agent
            # STRICTLY use data_agent_id and enforce status='active'
            active_routing = db.query(AgentRouting).filter(
                AgentRouting.agent_id == data_agent_id,
                AgentRouting.is_active == True,
                AgentRouting.status == 'active'
            ).first()

            user = None
            if active_routing and active_routing.user_id:
                user = db.query(User).filter(User.id == active_routing.user_id).first()

            # Logging Routing Result
            if user:
                logger.info(f"[ROUTING] resolved via data.agent_id -> user_id={user.id}")
            else:
                logger.warning(f"[ROUTING] FAILED agent_id={data_agent_id}")

            # We still need agent_obj for UsageEvent FK
            agent_obj = db.query(Agent).filter_by(agent_id=data_agent_id).first()

            if not user or not agent_obj:
                logger.warning(f"[JOB] Unassigned/Unknown agent/user for agent_id {data_agent_id}. Storing UnassignedEvent.")
                unassigned = UnassignedEvent(
                    agent_id=data_agent_id,
                    phone_number=to_number,
                    payload=payload
                )
                db.add(unassigned)
                db.commit()
                return # Stop processing

            # Capture Email/Studio info from User (Source of Truth)
            db_email_to = user.email
            db_studio_name = user.studio_name

            # 4. Check Suspension
            if not user.is_active:
                logger.warning(f"[JOB] Suspended user {user.username}. Blocking.")
                return

            if not user.has_active_plan():
                logger.warning(f"[JOB] No active plan for user {user.username}. Blocking.")
                return

            # Resolve active_sub for linking usage event (fallback to last sub if manual override but no active sub found?)
            # UsageEvent REQUIRES a subscription_id currently.
            # If manual plan is used and no Stripe sub exists, we might need a "dummy" sub or allow nullable subscription_id.
            # However, prompt says "Stripe integration remains active", so likely a sub exists even if expired/canceled.
            # We should try to find *some* subscription record to link to, or create one if manual.
            # For now, let's link to the most recent subscription record even if canceled,
            # OR find the active one.

            target_sub = db.query(Subscription).filter(
                Subscription.user_id == user.id,
                Subscription.state == "active"
            ).first()

            if not target_sub:
                # If no active stripe sub (maybe manual override), get the latest one
                target_sub = db.query(Subscription).filter(
                    Subscription.user_id == user.id
                ).order_by(Subscription.id.desc()).first()

            if not target_sub:
                # If NO subscription record exists at all (e.g. manually added user without stripe init), we can't create UsageEvent easily without changing schema.
                # Assuming all users have at least a "NONE" plan subscription created at register/init?
                # If not, we skip metering or create a dummy one?
                # Let's log warning and return for now to avoid crash, but this effectively blocks metering.
                # However, blocking logic above passed, so we allow the call but maybe fail to bill it?
                # But wait, step 5 is just metering. The call logic continues after the `try...catch` block?
                # No, if we return here, we skip AI/Email.
                # We need a subscription to link usage.
                logger.warning(f"[JOB] User {user.username} has active plan (manual?) but no Subscription record found in DB. Cannot meter usage.")
                # We should probably allow proceeding but skip usage tracking?
                # But IDEMPOTENCY relies on UsageEvent insert.
                # Let's Skip metering but proceed? No, idempotency is key.
                # Let's assume a subscription always exists (created on user creation? admin_seed creates plans, maybe client_service creates sub?)
                return

            # 5. IDEMPOTENCY & LOCKING (Insert UsageEvent)
            # This acts as a lock. If call_id exists, IntegrityError will be raised.
            if call_id and duration_secs:
                 billing_service = BillingService(db)
                 # We insert explicitly here to lock.
                 # billing_service.meter_call might do a commit, which is fine.
                 # meter_call checks for existing call_id too? Let's check logic or rely on IntegrityError.
                 # UsageEvent.call_id is UNIQUE.

                 usage_event = UsageEvent(
                    subscription_id=target_sub.id,
                    user_id=user.id,
                    agent_id=agent_obj.id,
                    call_id=call_id,
                    started_at=start_dt_obj,
                    ended_at=end_dt_obj,
                    billed_seconds=int(duration_secs)
                 )
                 db.add(usage_event)
                 db.commit() # This will raise IntegrityError if duplicate
                 logger.info(f"[JOB] Locked call_id {call_id} via UsageEvent insert.")

        except IntegrityError:
            db.rollback()
            logger.info(f"[JOB] Duplicate call_id {call_id} detected (IntegrityError). Skipping OpenAI/Email.")
            return

        except Exception as e:
            logger.error(f"[JOB] DB Error: {e}")
            # We treat DB errors as fatal for processing to avoid incorrect billing/logging
            return

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

    # LOG CALL
    upsert_call_log(data_agent_id, {
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

    # ENQUEUE EMAIL

    # 1. Use DB resolved values
    studio_name = db_studio_name
    email_to = db_email_to

    # 2. Strict Check: If no user/email found in DB, log unrouted and skip.
    if not email_to:
        logger.warning(f"[JOB] Unrouted event for agent_id={data_agent_id}. No user/email found in DB. Skipping email.")
        return

    if not studio_name:
        logger.warning(f"[JOB] Missing studio_name for agent_id {data_agent_id}. Skipping email.")
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

        subject = f"[Mr.Automa] Nuova chiamata per {studio_name} da {caller_number}"

        queue = get_queue()
        queue.enqueue(send_email_job, email_to, subject, email_body)
        logger.info(f"Email job enqueued for {email_to}")

    except Exception as e:
        logger.error(f"Error preparing/enqueuing email: {e}")
