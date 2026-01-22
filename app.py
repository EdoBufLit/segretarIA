import os
import json
import uuid
import sentry_sdk
from datetime import datetime
from typing import Any, Dict, Optional, List
from pydantic import BaseModel
from fastapi import FastAPI, HTTPException, Request, Body, Query, Response
from fastapi.responses import HTMLResponse, StreamingResponse
from dotenv import load_dotenv
from mailer import send_email
from openai import OpenAI
import logging
from logging_config import configure_logging, correlation_id
from pathlib import Path
from fastapi.staticfiles import StaticFiles
from datetime import datetime, date, timedelta
from openai import OpenAI
from starlette.middleware.sessions import SessionMiddleware
from fastapi.responses import RedirectResponse
from fastapi import Form, Depends
from fastapi.templating import Jinja2Templates
import httpx
from sqlalchemy.orm import Session
from sqlalchemy import text
from db import get_db, SessionLocal
from models import User
from auth import verify_password, get_current_user, get_current_admin_user
from admin_service import AdminService
from client_service import ClientService
from billing_service import BillingService
from backup_db import perform_backup, enforce_retention
from stripe_service import StripeService
from models import Agent, Subscription
from queue_utils import get_queue, get_redis_connection
from jobs.email_jobs import send_email_job
from jobs.stripe_jobs import process_stripe_event_job
from jobs.eleven_jobs import process_elevenlabs_event_job
from call_utils import extract_transcript_text, summarize_call, build_email_body_html, enrich_call_with_ai, log_call
# ================== CONFIG BASE ==================

load_dotenv()
templates = Jinja2Templates(directory="templates")

# Configure Logging
configure_logging()
# Get structlog logger? Or use stdlib which is now intercepted
logger = logging.getLogger("app")

# Sentry
SENTRY_DSN = os.getenv("SENTRY_DSN")
if SENTRY_DSN:
    sentry_sdk.init(
        dsn=SENTRY_DSN,
        # Set traces_sample_rate to 1.0 to capture 100%
        # of transactions for performance monitoring.
        traces_sample_rate=1.0,
    )

app = FastAPI()
app.add_middleware(
    SessionMiddleware,
    secret_key=os.getenv("SESSION_SECRET", "super-secret-change-me"),
)

@app.middleware("http")
async def add_correlation_id(request: Request, call_next):
    request_id = request.headers.get("X-Request-ID", str(uuid.uuid4()))
    token = correlation_id.set(request_id)
    # Bind to Sentry
    if SENTRY_DSN:
        sentry_sdk.set_tag("correlation_id", request_id)

    response = await call_next(request)
    response.headers["X-Request-ID"] = request_id

    correlation_id.reset(token)
    return response

app.mount("/static", StaticFiles(directory="static"), name="static")


@app.on_event("startup")
async def startup_event():
    """
    Run database backup and retention policy on application startup.
    """
    try:
        logger.info("Starting database backup...")
        perform_backup()
        enforce_retention()
        logger.info("Database backup and retention policy enforcement completed.")
    except Exception as e:
        logger.error(f"Error during database backup on startup: {e}")

# Nome della TUA agency / servizio, non del singolo studio
STUDIO_NAME = os.getenv("STUDIO_NAME", "Segreteria IA")

# Email mittente (la tua)
EMAIL_FROM = os.getenv("EMAIL_FROM")  # es: "Segreteria IA <edo.buffa9898@gmail.com>"
EMAIL_TO_FALLBACK = os.getenv("EMAIL_TO")  # nel dubbio
ELEVEN_API_KEY = os.getenv("ELEVEN_API_KEY")
SMTP_HOST = os.getenv("SMTP_HOST", "smtp.gmail.com")
SMTP_PORT = int(os.getenv("SMTP_PORT", "587"))
SMTP_USER = os.getenv("SMTP_USER")
SMTP_PASSWORD = os.getenv("SMTP_PASSWORD")
ADMIN_USERNAME = os.getenv("ADMIN_USERNAME", "admin")
ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD", "password123")

# ================== CONFIG MULTI-CLIENT (clients.json) ==================
CLIENTS_FILE = os.getenv("CLIENTS_FILE", "clients.json")
CLIENTS: Dict[str, Dict[str, Any]] = {}
CLIENTS_MTIME: Optional[float] = None
LOGS_DIR = Path("logs")
LOGS_DIR.mkdir(exist_ok=True)

class ClientSettingsUpdate(BaseModel):
    studio_name: str | None = None
    email_to: str | None = None
    greeting: str | None = None
    notes: str | None = None
    agent_phone_number_id: str | None = None   # ID numero collegato in ElevenLabs
    test_phone_number: str | None = None       # Numero di test (es. tuo cellulare)



def load_clients() -> Dict[str, Dict[str, Any]]:
    """
    Carica la mappa agent_id -> config cliente da clients.json
    e aggiorna il timestamp globale CLIENTS_MTIME.
    """
    global CLIENTS_MTIME

    path = Path(CLIENTS_FILE)
    if not path.exists():
        logger.warning(f"[CLIENTS] File {CLIENTS_FILE} non trovato. Uso mapping vuoto.")
        CLIENTS_MTIME = None
        return {}

    try:
        with path.open("r", encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data, dict):
            raise TypeError("clients.json deve contenere un oggetto JSON")

        CLIENTS_MTIME = path.stat().st_mtime
        logger.info(f"[CLIENTS] Caricati {len(data)} client da {CLIENTS_FILE}. mtime={CLIENTS_MTIME}")
        return data
    except Exception as e:
        logger.exception(f"[CLIENTS] Errore caricando {CLIENTS_FILE}: {e}")
        return {}



# Carica una volta all'avvio
CLIENTS = load_clients()

def maybe_reload_clients() -> None:
    """
    Controlla se clients.json è cambiato su disco.
    Se sì, ricarica CLIENTS.
    """
    global CLIENTS, CLIENTS_MTIME

    path = Path(CLIENTS_FILE)
    if not path.exists():
        return

    try:
        current_mtime = path.stat().st_mtime
    except Exception as e:
        logger.warning(f"[CLIENTS] Impossibile leggere mtime di {CLIENTS_FILE}: {e}")
        return

    if CLIENTS_MTIME is None or current_mtime != CLIENTS_MTIME:
        logger.info("[CLIENTS] Rilevato cambiamento in clients.json, ricarico...")
        CLIENTS = load_clients()

@app.get("/clients/{agent_id}")
async def get_client(agent_id: str):
    maybe_reload_clients()
    if agent_id not in CLIENTS:
        raise HTTPException(status_code=404, detail="Cliente non trovato")
    return {"status": "ok", "client": CLIENTS[agent_id]}


@app.post("/clients/{agent_id}/update")
async def update_client(agent_id: str, payload: ClientSettingsUpdate):
    maybe_reload_clients()
    if agent_id not in CLIENTS:
        raise HTTPException(status_code=404, detail="Cliente non trovato")

    client = CLIENTS[agent_id]

    if payload.studio_name is not None:
        client["studio_name"] = payload.studio_name
    if payload.email_to is not None:
        client["email_to"] = payload.email_to
    if payload.greeting is not None:
        client["greeting"] = payload.greeting
    if payload.notes is not None:
        client["notes"] = payload.notes
    # 🔥 nuovi campi:
    if payload.agent_phone_number_id is not None:
        client["agent_phone_number_id"] = payload.agent_phone_number_id
    if payload.test_phone_number is not None:
        client["test_phone_number"] = payload.test_phone_number

    with open(CLIENTS_FILE, "w", encoding="utf-8") as f:
        json.dump(CLIENTS, f, indent=2, ensure_ascii=False)

    maybe_reload_clients()
    return {"status": "ok", "client": client}




def get_client_config(agent_id: Optional[str]) -> Dict[str, Any]:
    """
    Ritorna la configurazione cliente a partire da agent_id.
    Se non trova nulla, usa il fallback (singolo studio).
    """
    if agent_id and agent_id in CLIENTS:
        cfg = CLIENTS[agent_id]
        studio_name = cfg.get("studio_name", STUDIO_NAME)
        email_to = cfg.get("email_to", EMAIL_TO_FALLBACK)
        logger.info(f"[ROUTING] Trovato client per agent_id={agent_id}: {studio_name} -> {email_to}")
    else:
        logger.warning(f"[ROUTING] Nessun client configurato per agent_id={agent_id}, uso fallback.")
        studio_name = STUDIO_NAME
        email_to = EMAIL_TO_FALLBACK

    if not email_to:
        raise RuntimeError(
            "Nessuna email di destinazione configurata: "
            "controlla clients.json o la variabile di ambiente EMAIL_TO."
        )

    return {
        "studio_name": studio_name,
        "email_to": email_to,
    }

# ================== HEALTH ENDPOINTS ==================

@app.get("/health")
async def health_check():
    return {"status": "ok"}

@app.get("/ready")
async def readiness_check(db: Session = Depends(get_db)):
    # Check Database
    try:
        db.execute(text("SELECT 1"))
        db_status = "ok"
    except Exception as e:
        logger.error(f"Readiness check failed (DB): {e}")
        db_status = "failed"
        return Response(status_code=503, content=json.dumps({"status": "failed", "db": db_status}), media_type="application/json")

    # Check Redis
    redis_status = "ok"
    try:
        redis = get_redis_connection()
        redis.ping()
    except Exception as e:
        logger.error(f"Readiness check failed (Redis): {e}")
        redis_status = "failed"
        # Redis might be optional depending on config, but if configured, we should check.
        # Assuming Redis is critical for async jobs.
        return Response(status_code=503, content=json.dumps({"status": "failed", "db": db_status, "redis": redis_status}), media_type="application/json")

    return {"status": "ok", "db": db_status, "redis": redis_status}


# ================== ENDPOINT DI TEST ==================

@app.get("/", response_class=HTMLResponse)
async def root(request: Request):
    user = request.session.get("user")
    return templates.TemplateResponse("index.html", {"request": request, "user": user})


# ================== ADMIN ENDPOINTS ==================

@app.get("/admin/clients", response_class=HTMLResponse)
async def admin_get_clients(request: Request, db: Session = Depends(get_db), admin: User = Depends(get_current_admin_user)):
    service = AdminService(db)
    clients = service.get_clients()
    return templates.TemplateResponse("admin_clients.html", {"request": request, "clients": clients})

@app.post("/admin/clients/create")
async def admin_create_client(username: str = Form(...), email: str = Form(...), password: str = Form(...), studio_name: str = Form(...), db: Session = Depends(get_db), admin: User = Depends(get_current_admin_user)):
    service = AdminService(db)
    try:
        client = service.create_client(username, email, password, studio_name)
        service.sync_clients_to_json()
        return {"status": "ok", "client_id": client.id}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

@app.post("/admin/agents/create")
async def admin_create_agent(agent_id: str = Form(...), display_name: str = Form(...), phone_number_id: str = Form(None), db: Session = Depends(get_db), admin: User = Depends(get_current_admin_user)):
    service = AdminService(db)
    try:
        agent = service.create_agent(agent_id, display_name, phone_number_id)
        service.sync_clients_to_json()
        return {"status": "ok", "agent_id": agent.id}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

@app.post("/admin/clients/{user_id}/assign-agent")
async def admin_assign_agent(user_id: int, agent_id: int = Form(...), db: Session = Depends(get_db), admin: User = Depends(get_current_admin_user)):
    service = AdminService(db)
    try:
        client = service.assign_agent_to_client(user_id, agent_id)
        service.sync_clients_to_json()
        return {"status": "ok", "client_id": client.id, "assigned_agents": [a.id for a in client.agents]}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

@app.post("/admin/clients/{user_id}/create-subscription")
async def admin_create_subscription(user_id: int, plan_code: str = Form(...), db: Session = Depends(get_db), admin: User = Depends(get_current_admin_user)):
    service = AdminService(db)
    try:
        subscription = service.create_or_update_subscription(user_id, plan_code)
        return {"status": "ok", "subscription_id": subscription.id, "state": subscription.state}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

@app.post("/admin/sync-clients-json")
async def admin_sync_clients_json(db: Session = Depends(get_db), admin: User = Depends(get_current_admin_user)):
    service = AdminService(db)
    summary = service.sync_clients_to_json()
    return {"status": "ok", **summary}

@app.get("/admin/phone-numbers", response_class=HTMLResponse)
async def admin_get_phone_numbers(request: Request, db: Session = Depends(get_db), admin: User = Depends(get_current_admin_user)):
    service = AdminService(db)
    numbers = service.get_all_phone_numbers()
    return templates.TemplateResponse("admin_phonenumbers.html", {"request": request, "numbers": numbers})

@app.post("/admin/phone-numbers/create") # Temporary for testing
async def admin_create_phone_number(e164: str = Form(...), user_id: int = Form(...), db: Session = Depends(get_db), admin: User = Depends(get_current_admin_user)):
    service = AdminService(db)
    try:
        phone = service.create_phone_number(e164, user_id)
        return {"status": "ok", "phone_number_id": phone.id}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

@app.post("/admin/phone-numbers/{phone_id}/mark-released")
async def admin_mark_phone_number_released(phone_id: int, db: Session = Depends(get_db), admin: User = Depends(get_current_admin_user)):
    service = AdminService(db)
    try:
        service.mark_phone_number_released(phone_id)
        return RedirectResponse(url="/admin/phone-numbers", status_code=303)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))

@app.post("/admin/phone-numbers/{phone_id}/cancel-deprovision")
async def admin_cancel_deprovision(phone_id: int, db: Session = Depends(get_db), admin: User = Depends(get_current_admin_user)):
    service = AdminService(db)
    try:
        service.cancel_phone_number_deprovisioning(phone_id)
        return RedirectResponse(url="/admin/phone-numbers", status_code=303)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@app.post("/admin/users/{user_id}/reset-password")
async def admin_reset_password(user_id: int, db: Session = Depends(get_db), admin: User = Depends(get_current_admin_user)):
    service = AdminService(db)
    try:
        new_password = service.reset_password_random(user_id, admin.username)
        # We might return it to the admin so they can see it if needed,
        # or just confirm it was sent.
        return {"status": "ok", "message": "Password reset successfully. Email sent.", "new_password": new_password}
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@app.get("/admin/export/minutes")
async def admin_export_minutes(
    from_date: str = Query(..., alias="from"),
    to_date: str = Query(..., alias="to"),
    db: Session = Depends(get_db),
    admin: User = Depends(get_current_admin_user)
):
    """
    Exports usage minutes to CSV.
    """
    service = AdminService(db)
    try:
        # Parse dates (expecting ISO or YYYY-MM-DD)
        # If they come as YYYY-MM-DD, we can assume start of day / end of day
        try:
            fd = datetime.fromisoformat(from_date)
        except ValueError:
            fd = datetime.strptime(from_date, "%Y-%m-%d")

        try:
            td = datetime.fromisoformat(to_date)
            # If input was just YYYY-MM-DD (len 10), fromisoformat returns midnight.
            # We want inclusive end date for logs/minutes.
            if len(to_date) == 10:
                 td = td.replace(hour=23, minute=59, second=59)
        except ValueError:
            td = datetime.strptime(to_date, "%Y-%m-%d")
            td = td.replace(hour=23, minute=59, second=59)

        return StreamingResponse(
            service.export_minutes_csv_generator(fd, td, admin.username),
            media_type="text/csv",
            headers={"Content-Disposition": f"attachment; filename=minutes_{from_date}_{to_date}.csv"}
        )
    except Exception as e:
        logger.exception("Export minutes failed")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/admin/export/logs")
async def admin_export_logs(
    from_date: str = Query(..., alias="from"),
    to_date: str = Query(..., alias="to"),
    client: Optional[str] = None,
    db: Session = Depends(get_db),
    admin: User = Depends(get_current_admin_user)
):
    """
    Exports logs to CSV.
    """
    service = AdminService(db)
    try:
        try:
            fd = datetime.fromisoformat(from_date)
        except ValueError:
            fd = datetime.strptime(from_date, "%Y-%m-%d")

        try:
            td = datetime.fromisoformat(to_date)
            if len(to_date) == 10:
                 td = td.replace(hour=23, minute=59, second=59)
        except ValueError:
            td = datetime.strptime(to_date, "%Y-%m-%d")
            td = td.replace(hour=23, minute=59, second=59)

        return StreamingResponse(
            service.export_logs_csv_generator(fd, td, client, admin.username),
            media_type="text/csv",
            headers={"Content-Disposition": f"attachment; filename=logs_{from_date}_{to_date}.csv"}
        )
    except Exception as e:
        logger.exception("Export logs failed")
        raise HTTPException(status_code=500, detail=str(e))


# ================== CLIENT ENDPOINTS ==================

@app.get("/subscription/status")
async def get_subscription_status(db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    service = ClientService(db, current_user)
    status = service.get_subscription_status()
    return status

@app.post("/subscription/cancel")
async def cancel_subscription(db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    service = ClientService(db, current_user)
    try:
        result = service.cancel_subscription()
        return result
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.post("/billing/checkout")
async def create_checkout_session(
    plan_code: str = Body(..., embed=True),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    service = StripeService(db)
    try:
        # Assuming we have a configured base URL or use request headers
        base_url = os.getenv("BASE_URL", "http://127.0.0.1:8000")
        success_url = f"{base_url}/dashboard?checkout=success"
        cancel_url = f"{base_url}/dashboard?checkout=cancel"

        session = service.create_checkout_session(
            user_id=current_user.id,
            plan_code=plan_code,
            success_url=success_url,
            cancel_url=cancel_url
        )
        return {"status": "ok", "checkout_url": session.url}
    except Exception as e:
        logger.exception("Checkout creation failed")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/stripe/webhook")
async def stripe_webhook(request: Request, db: Session = Depends(get_db)):
    payload = await request.body()
    sig_header = request.headers.get("stripe-signature")

    service = StripeService(db)
    try:
        # Verify and extract data
        event_type, data = service.verify_webhook_event(payload, sig_header)

        # Enqueue processing
        try:
            queue = get_queue()
            queue.enqueue(process_stripe_event_job, event_type, data)
            logger.info(f"[STRIPE] Job enqueued: {event_type}")
        except Exception as e:
            logger.error(f"[STRIPE] Failed to enqueue job (Redis down?): {e}")
            # Fallback: Process sync if queue fails?
            # Or just fail? For reliability, we might want sync fallback.
            # But task says "Make Stripe webhook handler async via queue".
            # If queue is down, we can return 500 so Stripe retries later.
            raise HTTPException(status_code=500, detail="Queue unavailable")

        return {"status": "received"}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Stripe webhook failed")
        raise HTTPException(status_code=500, detail="Internal Server Error")


# ================== WEBHOOK ELEVENLABS ==================

@app.post("/elevenlabs/webhook")
async def elevenlabs_webhook(request: Request):
    """
    Webhook ElevenLabs.
    """
    # Controlla se clients.json è cambiato e, se sì, ricarica
    maybe_reload_clients()
    raw_body = await request.body()
    payload = json.loads(raw_body.decode("utf-8"))

    # estrai transcript
    transcript_text = extract_transcript_text(payload)

    # arricchimento AI
    ai_data = enrich_call_with_ai(transcript_text)

    # quando costruisci l'entry di log:
    entry = {
        "timestamp": datetime.utcnow().isoformat(),
        "data": payload,
        "transcript_text": transcript_text,
        "ai_enrichment": ai_data,
    }
    # 1) Body grezzo
    try:
        raw_body = await request.body()
        body_str = raw_body.decode("utf-8", errors="replace")
    except Exception as e:
        logger.exception("[WEBHOOK] Errore lettura body")
        return {"status": "ignored", "reason": f"body read error: {e}"}

    if not body_str.strip():
        logger.warning("[WEBHOOK] Body vuoto.")
        return {"status": "ignored", "reason": "empty body"}

    # 2) JSON
    try:
        payload = json.loads(body_str)
    except json.JSONDecodeError as e:
        logger.exception("[WEBHOOK] JSON non valido")
        return {"status": "ignored", "reason": f"invalid json: {e}"}

    logger.info("[WEBHOOK] Payload ElevenLabs ricevuto")

    # 3) Tipo evento
    event_type = payload.get("type")
    if event_type != "post_call_transcription":
        logger.info(f"[WEBHOOK] Ignoro evento di tipo {event_type}")
        return {"status": "ignored", "reason": f"unsupported type {event_type}"}

    data: Dict[str, Any] = payload.get("data", {}) or {}

    # 3b) Agent ID (chi identifica il cliente)
    agent_id: Optional[str] = data.get("agent_id")

    # Metadati chiamata
    metadata: Dict[str, Any] = data.get("metadata", {}) or {}
    start_unix = metadata.get("start_time_unix_secs")
    duration_secs = metadata.get("call_duration_secs")

    started_at: Optional[str] = None
    ended_at: Optional[str] = None

    try:
        if isinstance(start_unix, (int, float)):
            started_dt = datetime.utcfromtimestamp(start_unix)
            started_at = started_dt.isoformat()
            if isinstance(duration_secs, (int, float)):
                ended_dt = datetime.utcfromtimestamp(start_unix + duration_secs)
                ended_at = ended_dt.isoformat()
    except Exception as e:
        logger.warning(f"[WEBHOOK] Errore calcolo orari chiamata: {e}")

    # ENFORCEMENT & IDEMPOTENCY
    with SessionLocal() as db:
        agent_obj = db.query(Agent).filter_by(agent_id=agent_id).first()
        if agent_obj:
            # Find owner (Client)
            user = db.query(User).filter(User.agents.contains(agent_obj)).first()

            # Check User Active
            if user and not user.is_active:
                logger.warning(f"[WEBHOOK] Suspended user {user.username} (agent {agent_id}). Blocking.")
                return {"status": "suspended"}

            # Check Subscription Active
            if user:
                active_sub = db.query(Subscription).filter(
                    Subscription.user_id == user.id,
                    Subscription.state == "active"
                ).first()
                if not active_sub:
                    logger.warning(f"[WEBHOOK] No active subscription for user {user.username} (agent {agent_id}). Blocking.")
                    return {"status": "suspended"}

        # IDEMPOTENCY CHECK
        if duration_secs and agent_id:
            call_id = metadata.get("phone_call", {}).get("call_sid") or data.get("conversation_id")
            if call_id:
                from models import UsageEvent
                exists = db.query(UsageEvent).filter_by(call_id=call_id).first()
                if exists:
                    logger.info(f"[WEBHOOK] Duplicate call_id {call_id}. Idempotency check passed. Skipping.")
                    return {"status": "ok", "message": "Duplicate event ignored"}

    # Enqueue processing job
    try:
        queue = get_queue()
        queue.enqueue(process_elevenlabs_event_job, payload)
        logger.info(f"[WEBHOOK] Job enqueued for agent {agent_id}")
    except Exception as e:
        logger.error(f"[WEBHOOK] Failed to enqueue job (Redis down?): {e}")
        # Fallback logic could be added here, but for now we return 200
        # and rely on the queue. In real prod, might return 500 to trigger retry.
        # Given requirement to return fast response, we accept queue dependency.
        raise HTTPException(status_code=500, detail="Queue unavailable")

    return {"status": "ok", "message": "Webhook received and processing enqueued."}

@app.get("/clients")
async def list_clients():
    """
    Restituisce la lista dei client configurati (agent_id -> dati).
    Prima ricarica dinamicamente clients.json se è cambiato.
    """
    maybe_reload_clients()

    from copy import deepcopy
    visible_clients = deepcopy(CLIENTS)

    return {
        "status": "ok",
        "count": len(visible_clients),
        "mtime": CLIENTS_MTIME,
        "clients": visible_clients,
    }


def save_clients_to_file():
    """Scrive CLIENTS su clients.json."""
    path = Path(CLIENTS_FILE)
    with path.open("w", encoding="utf-8") as f:
        json.dump(CLIENTS, f, indent=2, ensure_ascii=False)
    logger.info("[CLIENTS] Salvato clients.json aggiornato.")


@app.post("/clients/add")
async def add_client(
    agent_id: str = Body(...),
    studio_name: str = Body(...),
    email_to: str = Body(...)
):
    """
    Aggiunge un nuovo cliente a clients.json.
    """
    maybe_reload_clients()

    if agent_id in CLIENTS:
        return {"status": "error", "message": "Client già esistente."}

    CLIENTS[agent_id] = {
        "studio_name": studio_name,
        "email_to": email_to
    }

    save_clients_to_file()
    maybe_reload_clients()

    return {"status": "ok", "message": "Cliente aggiunto.", "client": CLIENTS[agent_id]}


class RemoveClientRequest(BaseModel):
    agent_id: str

@app.post("/clients/remove")
async def remove_client(body: RemoveClientRequest):
    maybe_reload_clients()

    agent_id = body.agent_id

    if agent_id not in CLIENTS:
        return {"status": "error", "message": "Client non trovato."}

    # Rimuovi dal dizionario
    CLIENTS.pop(agent_id)

    # Riscrivi il file
    with open(CLIENTS_FILE, "w", encoding="utf-8") as f:
        json.dump(CLIENTS, f, indent=4, ensure_ascii=False)

    return {"status": "ok", "message": f"Client {agent_id} rimosso correttamente."}


@app.get("/logs/{agent_id}/list")
async def view_logs_list(
    agent_id: str,
    limit: int = 50,
    offset: int = 0,
    status: Optional[str] = None,
    q: Optional[str] = None,
    # date_from, date_to ... si possono aggiungere
):
    """
    Restituisce i log impaginati e filtrabili per la dashboard.
    """
    maybe_reload_clients()
    
    log_path = LOGS_DIR / f"{agent_id}.log"
    if not log_path.exists():
        return {"items": [], "total": 0}
        
    all_logs = []
    with log_path.open("r", encoding="utf-8") as f:
        for line in f:
            try:
                entry = json.loads(line)
                inner_data = entry.get("data", {})
                
                # Se c'è un filtro 'q' (search)
                if q:
                    # Cerca in caller_number, summary, analysis
                    search_content = f"{inner_data.get('caller_number','')} {inner_data.get('summary','')} {str(inner_data.get('analysis',''))}".lower()
                    if q.lower() not in search_content:
                        continue
                        
                # Se c'è un filtro status
                row_status = inner_data.get("status", "success")
                if status and status != "all":
                    if row_status != status:
                        continue
                
                item = {
                    "timestamp": entry.get("timestamp"),
                    "caller": inner_data.get("caller_number", "Unknown"),
                    "status": row_status,
                    "duration_secs": inner_data.get("duration_secs"),
                    "summary": inner_data.get("summary") or inner_data.get("analysis", {}).get("summary", ""),
                    "raw": entry
                }
                all_logs.append(item)
            except:
                pass
                
    # Ordinamento: dal più recente
    all_logs.reverse()
    
    total = len(all_logs)
    paginated = all_logs[offset : offset + limit]
    
    return {
        "items": paginated,
        "total": total
    }

@app.get("/logs/{agent_id}")
async def view_logs(agent_id: str):
    """
    Restituisce lo storico completo (legacy endpoint, o per debug).
    """
    maybe_reload_clients()

    log_path = LOGS_DIR / f"{agent_id}.log"
    if not log_path.exists():
        return {"status": "ok", "message": "Nessun log per questo client.", "logs": []}

    logs = []
    with log_path.open("r", encoding="utf-8") as f:
        for line in f:
            try:
                logs.append(json.loads(line))
            except:
                pass

    return {
        "status": "ok",
        "count": len(logs),
        "logs": logs
    }


@app.get("/analytics/global")
async def analytics_global():
    """
    Ritorna statistiche aggregate da TUTTI i log:
    - chiamate totali
    - chiamate per giorno
    - chiamate per cliente
    - chiamate oggi
    - chiamate ultimi 7 giorni
    - numero di errori/fallite
    - distribuzione per categoria / urgenza
    - heatmap oraria (24 x 7)
    """
    maybe_reload_clients()

    stats_by_day: Dict[str, int] = {}
    stats_by_client: Dict[str, int] = {}
    stats_by_category: Dict[str, int] = {}
    stats_by_urgency: Dict[str, int] = {}

    total_calls = 0
    errors = 0
    calls_today = 0
    calls_last_7 = 0

    today = date.today()
    last_7_start = today - timedelta(days=6)

    # heatmap[hour][weekday] – 24 ore x 7 giorni
    heatmap = [[0 for _ in range(7)] for _ in range(24)]

    for agent_id in CLIENTS:
        log_path = LOGS_DIR / f"{agent_id}.log"
        if not log_path.exists():
            continue

        with log_path.open("r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue

                # --- parse JSON ---
                try:
                    entry = json.loads(line)
                except Exception:
                    # riga corrotta, la saltiamo
                    continue

                ts = entry.get("timestamp")
                if not ts:
                    continue

                try:
                    dt = datetime.fromisoformat(ts)
                except Exception:
                    continue

                total_calls += 1

                # ---- per giorno ----
                day_str = dt.date().isoformat()
                stats_by_day[day_str] = stats_by_day.get(day_str, 0) + 1

                # ---- per cliente ----
                stats_by_client[agent_id] = stats_by_client.get(agent_id, 0) + 1

                # ---- oggi / ultimi 7 giorni ----
                d = dt.date()
                if d == today:
                    calls_today += 1
                if d >= last_7_start:
                    calls_last_7 += 1

                # ---- errori / fallite ----
                # 1) Check status in log data (nested)
                inner_data = entry.get("data", {})
                status = inner_data.get("status")
                
                if status == "failure":
                    errors += 1
                elif status == "success":
                    pass
                else:
                    # 2) Fallback logic (old logs)
                    # inner_data is already entry.get("data")
                    analysis = inner_data.get("analysis", {})
                    call_successful = None
                    termination_reason = None
                    if isinstance(analysis, dict):
                        call_successful = analysis.get("call_successful")
                        termination_reason = analysis.get("termination_reason")

                    if call_successful == "failure" or termination_reason:
                        errors += 1

                # ---- AI enrichment (categoria / urgenza) ----
                ai = entry.get("ai_enrichment", {})
                cat = ai.get("category", "altro")
                urg = ai.get("urgency", "media")

                stats_by_category[cat] = stats_by_category.get(cat, 0) + 1
                stats_by_urgency[urg] = stats_by_urgency.get(urg, 0) + 1

                # ---- heatmap ora x giorno ----
                hour = dt.hour
                weekday = dt.weekday()  # 0 = Monday, 6 = Sunday
                if 0 <= hour < 24 and 0 <= weekday < 7:
                    heatmap[hour][weekday] += 1

    return {
        "status": "ok",
        "total_calls": total_calls,
        "by_day": stats_by_day,
        "by_client": stats_by_client,
        "calls_today": calls_today,
        "calls_last_7_days": calls_last_7,
        "errors": errors,
        "clients_count": len(CLIENTS),
        "heatmap": heatmap,
        "by_category": stats_by_category,
        "by_urgency": stats_by_urgency,
    }




@app.get("/analytics/{agent_id}")
async def analytics_client(agent_id: str):
    """
    Statistiche temporali solo per un client.
    Grafico linea → chiamate ordinate nel tempo.
    """
    log_path = LOGS_DIR / f"{agent_id}.log"
    if not log_path.exists():
        return {"status": "ok", "points": []}

    points = []
    with log_path.open("r", encoding="utf-8") as f:
        for line in f:
            try:
                entry = json.loads(line)
                points.append(entry["timestamp"])
            except:
                pass

    points.sort()
    return {
        "status": "ok",
        "points": points
    }



@app.get("/dashboard", response_class=HTMLResponse)
async def dashboard(request: Request, current_user: User = Depends(get_current_user)):
    if current_user.role == "admin":
        maybe_reload_clients()
        with open("templates/dashboard.html", "r", encoding="utf-8") as f:
            html = f.read()
        return HTMLResponse(content=html)
    else:
        return templates.TemplateResponse("client_portal.html", {"request": request})


@app.get("/logout")
async def logout(request: Request):
    request.session.clear()
    return RedirectResponse(url="/login", status_code=302)


@app.get("/me")
async def read_users_me(current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    # Find active subscription (or just the latest one)
    # We prioritize 'active' status. If none active, we take the most recent one.
    subscription_data = None

    # Simple query for active subscription first
    sub = db.query(Subscription).filter(
        Subscription.user_id == current_user.id,
        Subscription.state == "active"
    ).first()

    if not sub:
        # Fallback to any latest subscription
        sub = db.query(Subscription).filter(
            Subscription.user_id == current_user.id
        ).order_by(Subscription.created_at.desc()).first()

    if sub:
        subscription_data = {
            "state": sub.state,
            "plan_code": sub.plan.code if sub.plan else None,
            "cycle_end": sub.cycle_end.isoformat() if sub.cycle_end else None,
            "stripe_subscription_id": sub.stripe_subscription_id,
            "stripe_price_id": sub.stripe_price_id
        }

    return {
        "user": {
            "id": current_user.id,
            "username": current_user.username,
            "email": current_user.email,
            "role": current_user.role,
            "studio_name": current_user.studio_name,
            "is_active": current_user.is_active,
            "stripe_customer_id": current_user.stripe_customer_id
        },
        "subscription": subscription_data
    }


@app.get("/login", response_class=HTMLResponse)
async def login_form(request: Request):
    with open("templates/login.html", "r", encoding="utf-8") as f:
        html = f.read()
    return HTMLResponse(content=html)



@app.post("/login")
async def login_submit(
    request: Request,
    username: str = Form(...),
    password: str = Form(...),
    db: Session = Depends(get_db)
):
    user = db.query(User).filter(User.username == username).first()

    if not user or not user.is_active or not verify_password(password, user.password_hash):
        return RedirectResponse(url="/login?error=1", status_code=302)

    request.session["user"] = {
        "user_id": user.id,
        "username": user.username,
        "role": user.role,
    }
    return RedirectResponse(url="/dashboard", status_code=302)


@app.get("/logs/{agent_id}/list")
async def get_logs_filtered(
    agent_id: str,
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
    status: str = Query("all"),
    date_from: str = Query(None),
    date_to: str = Query(None),
    q: str = Query(None)
):
    """
    Ritorna i log del cliente in formato filtrabile e paginato:
    - limit, offset
    - status: all / success / failure
    - date_from, date_to (YYYY-MM-DD)
    - q: search su summary, caller, transcript
    """
    maybe_reload_clients()

    if agent_id not in CLIENTS:
        raise HTTPException(status_code=404, detail="Cliente non trovato")

    log_path = LOGS_DIR / f"{agent_id}.log"
    if not log_path.exists():
        return {"status": "ok", "total": 0, "items": []}

    items = []

    df = datetime.fromisoformat(date_from).date() if date_from else None
    dt = datetime.fromisoformat(date_to).date() if date_to else None

    with log_path.open("r", encoding="utf-8") as f:
        for line in f:
            try:
                raw = json.loads(line)
                ts = raw.get("timestamp")
                if not ts:
                    continue
                d = datetime.fromisoformat(ts)
                d_date = d.date()

                # --- FILTRO DATA ---
                if df and d_date < df:
                    continue
                if dt and d_date > dt:
                    continue

                # --- DETERMINA SUCCESS / FAILURE ---
                analysis = raw.get("data", {}).get("analysis", {})
                call_ok = analysis.get("call_successful")
                is_failure = (call_ok == "failure")

                if status == "success" and is_failure:
                    continue
                if status == "failure" and not is_failure:
                    continue

                # --- COSTRUZIONE ITEM ---
                item = {
                    "timestamp": ts,
                    "caller": raw.get("data", {}).get("user_id", "unknown"),
                    "status": "failure" if is_failure else "success",
                    "summary": raw.get("data", {}).get("analysis", {}).get("transcript_summary", "").strip(),
                    "duration_secs": raw.get("data", {}).get("metadata", {}).get("call_duration_secs", None),
                    "raw": raw  # per modal dettagliata
                }

                # --- SEARCH ---
                if q:
                    q_low = q.lower()
                    if q_low not in json.dumps(item, ensure_ascii=False).lower():
                        continue

                items.append(item)

            except:
                continue

    total = len(items)
    items = items[offset:offset + limit]

    return {"status": "ok", "total": total, "items": items}





    # …qui il tuo log_call(entry, agent_id) o simile…
    # …e la parte di email che già hai…
@app.post("/clients/{agent_id}/test-call")
async def test_call(agent_id: str, db: Session = Depends(get_db)):
    """
    Avvia una chiamata di test tramite ElevenLabs/Twilio verso il numero di test
    configurato per questo cliente.
    """
    # ENFORCEMENT: Check suspension
    agent_obj = db.query(Agent).filter_by(agent_id=agent_id).first()
    if agent_obj:
        user = db.query(User).filter(User.agents.contains(agent_obj)).first()
        if user and not user.is_active:
             raise HTTPException(status_code=403, detail="Service suspended due to payment failure.")

        # Check subscription
        if user:
            active_sub = db.query(Subscription).filter(
                Subscription.user_id == user.id,
                Subscription.state == "active"
            ).first()
            if not active_sub:
                 raise HTTPException(status_code=403, detail="No active subscription.")

    maybe_reload_clients()
    if agent_id not in CLIENTS:
        raise HTTPException(status_code=404, detail="Cliente non trovato")

    if not ELEVEN_API_KEY:
        raise HTTPException(status_code=500, detail="ELEVENLABS_API_KEY non configurata")

    client_cfg = CLIENTS[agent_id]

    # agent_id di ElevenLabs = agent_id delle nostre config (stiamo usando lo stesso)
    eleven_agent_id = agent_id
    phone_id = client_cfg.get("agent_phone_number_id")
    to_number = client_cfg.get("test_phone_number")

    if not phone_id or not to_number:
        raise HTTPException(
            status_code=400,
            detail="Config incompleta: serve agent_phone_number_id e test_phone_number nelle impostazioni del cliente"
        )

    url = "https://api.elevenlabs.io/v1/convai/twilio/outbound-call"
    headers = {
        "xi-api-key": ELEVEN_API_KEY,
        "Content-Type": "application/json",
    }
    body = {
        "agent_id": eleven_agent_id,
        "agent_phone_number_id": phone_id,
        "to_number": to_number,
        # opzionale: puoi passare variabili dinamiche
        "conversation_initiation_client_data": {
            "type": "conversation_initiation_client_data",
            "dynamic_variables": {
                "caller_name": "Test Edo",
                "test_call": True,
            }
        }
    }

    try:
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.post(url, headers=headers, json=body)
        if resp.status_code >= 400:
            print("Test call error:", resp.status_code, resp.text)
            raise HTTPException(
                status_code=resp.status_code,
                detail=f"Errore ElevenLabs: {resp.text}"
            )

        data = resp.json()
        # es: {'success': True, 'message': '...', 'conversation_id': '...', 'callSid': '...'}
        return {"status": "ok", "elevenlabs_response": data}

    except HTTPException:
        raise
    except Exception as e:
        print("Test call exception:", e)
        raise HTTPException(status_code=500, detail="Errore interno nella chiamata di test")
