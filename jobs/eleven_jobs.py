import json
import logging
from typing import Dict, Any, Optional
from datetime import datetime, timedelta
from sqlalchemy.exc import IntegrityError
from db import SessionLocal
from models import Agent, User, UsageEvent, PhoneNumber, AgentRouting, UnassignedEvent, Subscription
from jobs.email_jobs import send_email_job
from call_utils import upsert_call_log, summarize_call, build_email_body_html, extract_transcript_text
from queue_utils import get_queue
from services.subscription_service import ensure_subscription_for_user
from alerting import log_critical_error
import os

logger = logging.getLogger("eleven_jobs")
STUDIO_NAME = os.getenv("STUDIO_NAME", "Mr.Automa")
NOTIFICATION_EMAIL = os.getenv("NOTIFICATION_EMAIL")
MANUAL_PLAN_CODES = {"starter", "pro", "business"}

def upsert_agent_from_routing(db, routing: Optional[AgentRouting], user: Optional[User]) -> Optional[Agent]:
    if not routing or not routing.agent_id:
        return None

    agent = db.query(Agent).filter(Agent.agent_id == routing.agent_id).first()
    phone_number_id = str(routing.phone_number_id) if routing.phone_number_id else None

    if agent:
        if phone_number_id and agent.phone_number_id != phone_number_id:
            agent.phone_number_id = phone_number_id
        if not agent.display_name:
            agent.display_name = "Segreteria IA"
    else:
        agent = Agent(
            agent_id=routing.agent_id,
            phone_number_id=phone_number_id,
            display_name="Segreteria IA"
        )
        db.add(agent)
        db.flush()

    if user and agent not in user.agents:
        user.agents.append(agent)

    return agent

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
        data = payload.get("data") or {}
        agent_id = (data.get("agent_id") or "unknown").strip()
        # Safe extraction for error logging
        meta = data.get("metadata") or {}
        phone_meta = meta.get("phone_call") or {}
        call_id = (
            (phone_meta.get("call_sid") or phone_meta.get("callSid") or "").strip()
            or (data.get("conversation_id") or "").strip()
            or "unknown"
        )

        log_critical_error(f"Job fallito per agent_id {agent_id}: {e}", context={"agent_id": agent_id, "call_id": call_id})
        raise

def _process_elevenlabs_event_logic(payload: dict):
    event_type = (payload.get("type") or "").strip()
    data = payload.get("data") or {}
    conversation_id = (data.get("conversation_id") or "").strip()

    logger.info(f"Processing ElevenLabs event type={event_type} conversation_id={conversation_id}")

    agent_id = (data.get("agent_id") or "").strip()

    # We expect the payload to be already validated as 'post_call_transcription' by the endpoint.

    if not agent_id:
        logger.error("No agent_id in payload")
        return

    # Extract metadata safely
    metadata = data.get("metadata") or {}
    start_unix = metadata.get("start_time_unix_secs")
    duration_secs = metadata.get("call_duration_secs")

    # Branching logic by event type
    if event_type == "post_call_transcription":
        # For transcription events, metadata.phone_call is often missing/null
        phone_call_meta = metadata.get("phone_call") or {}
        call_id = (
            (phone_call_meta.get("call_sid") or phone_call_meta.get("callSid") or "").strip()
            or conversation_id
        )
        logger.info(f"[ELEVEN JOB] processed post_call_transcription conversation_id={conversation_id}")
    else:
        # Default behavior for other events
        phone_call_meta = metadata.get("phone_call") or {}
        call_id = (
            (phone_call_meta.get("call_sid") or phone_call_meta.get("callSid") or "").strip()
        )

    # Inbound Number (to_number)
    to_number = (phone_call_meta.get("number") or phone_call_meta.get("to_number") or "").strip()

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
    twilio_sid = (dyn.get("call_sid") or dyn.get("twilio_call_sid") or "").strip()

    if twilio_sid:
        call_id = twilio_sid
    elif not call_id:
        # Check explicit call_id in metadata
        call_id = (metadata.get("call_id") or "").strip()

    if not call_id:
        # Fallback if not set by branching logic
        call_id = conversation_id

    if not agent_id or not conversation_id:
        logger.warning(
            "[JOB] Missing identifiers agent_id=%s conversation_id=%s",
            agent_id or "missing",
            conversation_id or "missing"
        )

    # Calculate Timestamps early for UsageEvent
    # 1. Duration Calculation (with fallback to transcript)
    if not duration_secs:
        transcript = data.get("transcript") or []
        max_time = 0
        for turn in transcript:
            # Check various keys ElevenLabs might use
            time_in_call = turn.get("time_in_call_secs")
            if time_in_call and isinstance(time_in_call, (int, float)):
                if time_in_call > max_time:
                    max_time = time_in_call
        if max_time > 0:
            duration_secs = int(max_time)
            logger.info(f"[JOB] Calculated duration from transcript: {duration_secs}s")

    # 2. Timestamps
    started_at = None
    ended_at = None

    if isinstance(start_unix, (int, float)):
        started_dt = datetime.utcfromtimestamp(start_unix)
    else:
        # Fallback: End is now, Start is Now - Duration
        # If duration is missing, we can't infer much, assume 0 duration or now.
        dur = duration_secs or 0
        started_dt = datetime.utcnow() - timedelta(seconds=dur)

    started_at = started_dt.isoformat()
    start_dt_obj = started_dt

    if isinstance(duration_secs, (int, float)):
        ended_dt = started_dt + timedelta(seconds=duration_secs)
    else:
        ended_dt = datetime.utcnow()

    ended_at = ended_dt.isoformat()
    end_dt_obj = ended_dt

    # Variables for email sending (resolved via DB)
    db_email_to = None
    db_studio_name = None
    resolved_user_id = None

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

            # 3. Validation: Routing & User Resolution (Canonical)
            # Query active routing for this agent
            active_routing = db.query(AgentRouting).filter(
                AgentRouting.agent_id == agent_id,
                AgentRouting.is_active == True,
                AgentRouting.status == "active"
            ).order_by(AgentRouting.id.desc()).first()

            user = None
            resolved_user_id = None
            agent_obj = None
            if active_routing and active_routing.user_id:
                user = db.query(User).filter(User.id == active_routing.user_id).first()
                if user:
                    resolved_user_id = user.id
                    agent_obj = upsert_agent_from_routing(db, active_routing, user)

            # Logging Routing Result
            if user:
                logger.info(f"[ROUTING] agent_id={agent_id} -> user_id={user.id}")
            else:
                logger.warning(f"[ROUTING] FAILED agent_id={agent_id}")

            if not agent_obj:
                routing_source = active_routing or routing
                agent_obj = upsert_agent_from_routing(db, routing_source, user)

            if agent_obj:
                db.commit()

            if not user:
                logger.warning(f"[JOB] Unassigned agent_id={agent_id}. Storing UnassignedEvent.")
                unassigned = UnassignedEvent(
                    agent_id=agent_id,
                    phone_number=to_number,
                    payload=payload
                )
                db.add(unassigned)
                db.commit()

            # Capture Email/Studio info from User (Source of Truth)
            if user:
                db_email_to = user.email
                db_studio_name = user.studio_name

            # 4. Check Suspension
            if user and not user.is_active:
                logger.warning(f"[JOB] Suspended user {user.username}. Allowing summary/email to proceed.")

            if user and not user.has_active_plan():
                logger.warning(f"[JOB] No active plan for user {user.username}. Allowing summary/email to proceed.")

            # Resolve active_sub for linking usage event
            target_sub = None
            if user:
                # Ensure subscription exists (sync manual plan if needed)
                try:
                    target_sub = ensure_subscription_for_user(db, user.id)
                except Exception as e:
                    logger.error(f"Failed to ensure subscription for user {user.id}: {e}")
                    target_sub = None

                if not target_sub:
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
                    logger.warning(f"[JOB] User {user.username} has active plan but no Subscription record found. Skipping usage metering.")

            # 5. IDEMPOTENCY & LOCKING (Insert UsageEvent)
            if user and target_sub:
                # A) Resolve DB agent id
                db_agent = agent_obj
                if not db_agent:
                    logger.error("[USAGE] Agent not found for eleven_agent_id=%s", agent_id)
                    return

                # B) Resolve call_id (MUST be unique)
                call_id = conversation_id or agent_id

                # C) Compute billed_seconds
                billed_seconds = (metadata.get("call_duration_secs") or 0)
                if not billed_seconds:
                    billed_seconds = max(
                        (t.get("time_in_call_secs", 0) for t in (data.get("transcript") or [])),
                        default=0
                    )
                if billed_seconds is None:
                    billed_seconds = 0

                # D) Insert usage (idempotent)
                try:
                    usage = UsageEvent(
                        subscription_id=target_sub.id,
                        user_id=user.id,
                        agent_id=db_agent.id,
                        call_id=call_id,
                        billed_seconds=int(billed_seconds),
                        started_at=datetime.utcnow() - timedelta(seconds=billed_seconds),
                        ended_at=datetime.utcnow(),
                    )
                    db.add(usage)
                    db.commit()
                    logger.info("[USAGE] Inserted usage_event seconds=%s", billed_seconds)

                # E) Protect against duplicates
                except IntegrityError:
                    db.rollback()
                    logger.info(f"[JOB] Duplicate call_id {call_id} detected (IntegrityError). Skipping.")
                    return

        except Exception as e:
            logger.error(f"[JOB] DB Error: {e}")
            # We treat DB errors as fatal for processing to avoid incorrect billing/logging
            return

    # Extract transcript text
    transcript_text = extract_transcript_text(payload)

    # Status
    status = "success"
    if duration_secs and duration_secs < 3:
        status = "failure"

    # LOG CALL (initial insert)
    call_log_payload = {
        "conversation_id": conversation_id,
        "transcript_text": transcript_text,
        "caller_number": caller_number,
        "call_id": call_id,
        "started_at": started_at,
        "ended_at": ended_at,
        "duration_secs": duration_secs,
        "status": status
    }
    call_log_result = upsert_call_log(agent_id, call_log_payload, user_id=resolved_user_id)
    if call_log_result:
        if call_log_result.get("created"):
            logger.info(
                "[DB] call_log inserted id=%s user_id=%s agent_id=%s conversation_id=%s",
                call_log_result.get("id"),
                resolved_user_id,
                agent_id,
                conversation_id
            )
        else:
            logger.info(
                "[DB] call_log updated id=%s user_id=%s agent_id=%s conversation_id=%s",
                call_log_result.get("id"),
                resolved_user_id,
                agent_id,
                conversation_id
            )

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

    # LOG CALL (update with summary/analysis)
    call_log_payload.update({
        "analysis": analysis_structured,
        "summary": analysis_structured.get("summary")
    })
    upsert_call_log(agent_id, call_log_payload, user_id=resolved_user_id)

    # ENQUEUE EMAIL
    email_to = db_email_to
    studio_name = db_studio_name
    unassigned_prefix = ""

    if resolved_user_id:
        with SessionLocal() as db:
            u = db.query(User).filter(User.id == resolved_user_id).first()
            if u:
                if not email_to:
                    email_to = u.email
                if not studio_name:
                    studio_name = u.studio_name or u.username or STUDIO_NAME

    if not email_to:
        logger.warning(f"[JOB] Missing email for user_id={resolved_user_id}. Skipping email.")
        return

    if not studio_name:
        logger.warning(f"[JOB] Missing studio name for user_id={resolved_user_id}. Skipping email.")
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

        subject = f"{unassigned_prefix}[Mr.Automa] Nuova chiamata per {studio_name} da {caller_number}"

        queue = get_queue()
        queue.enqueue(send_email_job, email_to, subject, email_body)
        logger.info(f"[EMAIL] enqueued to={email_to} conversation_id={conversation_id}")

    except Exception as e:
        logger.error(f"Error preparing/enqueuing email: {e}")
