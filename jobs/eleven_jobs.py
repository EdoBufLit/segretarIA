import json
import logging
from typing import Dict, Any, Optional
from datetime import datetime, timedelta
from db import SessionLocal
from models import Agent, User, UsageEvent
from billing_service import BillingService
from jobs.email_jobs import send_email_job
from call_utils import log_call, summarize_call, build_email_body_html, extract_transcript_text, enrich_call_with_ai
from queue_utils import get_queue
import os

logger = logging.getLogger("eleven_jobs")
STUDIO_NAME = os.getenv("STUDIO_NAME", "Segreteria IA")

def process_elevenlabs_event_job(payload: dict):
    """
    Async job to process ElevenLabs webhook event:
    - Log call to file
    - Meter usage
    - Enqueue email
    """
    logger.info("Processing ElevenLabs event...")

    data = payload.get("data", {})
    agent_id = data.get("agent_id")
    if not agent_id:
        logger.error("No agent_id in payload")
        return

    # Extract metadata
    metadata = data.get("metadata", {})
    start_unix = metadata.get("start_time_unix_secs")
    duration_secs = metadata.get("call_duration_secs")
    caller_number = (
        metadata.get("phone_call", {}).get("external_number")
        or metadata.get("from_number")
        or metadata.get("caller_number")
        or metadata.get("phone_number")
        or "N/D"
    )

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

    # 6) Riassunto già fornito da ElevenLabs (se presente)
    analysis_obj: Dict[str, Any] = data.get("analysis", {}) or {}
    el_summary: Optional[str] = analysis_obj.get("transcript_summary")

    # 7) OpenAI per analisi strutturata
    try:
        analysis_structured = summarize_call(transcript_text, el_summary)
    except Exception as e:
        logger.warning(f"[OPENAI] Error in summarize_call: {e}")
        analysis_structured = {
            "summary": transcript_text,
            "client_name": None
        }

    # Determinazione status
    status = "success"
    if duration_secs and duration_secs < 3:
        status = "failure"

    # Extract call_id
    call_id = metadata.get("phone_call", {}).get("call_sid") or data.get("conversation_id")

    # LOG CALL
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

    # METERING
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
    email_to = os.getenv("EMAIL_TO") # Fallback

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

        # Enqueue
        queue = get_queue()
        queue.enqueue(send_email_job, email_to, subject, email_body)
        logger.info(f"Email job enqueued for {email_to}")

    except Exception as e:
        logger.error(f"Error preparing/enqueuing email: {e}")
