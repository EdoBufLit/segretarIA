import os
import json
import uuid
import secrets
import sentry_sdk
import re
from datetime import datetime
from typing import Any, Dict, Optional, List
from pydantic import BaseModel
from fastapi import FastAPI, HTTPException, Request, Body, Query, Response, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse, StreamingResponse, JSONResponse
from dotenv import load_dotenv
from mailer import send_email
from openai import OpenAI
import logging
import audit_logger
from logging_config import configure_logging, correlation_id
from pathlib import Path
import time
from fastapi.staticfiles import StaticFiles
from datetime import datetime, date, timedelta
from openai import OpenAI
from starlette.middleware.sessions import SessionMiddleware
from fastapi.responses import RedirectResponse
from fastapi import Form, Depends
from fastapi.templating import Jinja2Templates
import httpx
from sqlalchemy.orm import Session
from sqlalchemy import text, func
from db import get_db, SessionLocal
from models import User, Subscription, Plan, UsageEvent, PhoneNumber, AgentRouting, UnassignedEvent, PasswordResetToken, AgentSettings, CallLog, ChatMessage, Agent
import pytz
from auth import (
    hash_password,
    verify_password,
    get_current_user,
    get_current_admin_user,
    require_role,
    NotAuthenticatedPage,
    NotAuthorizedPage,
    get_current_user_page,
    get_current_admin_user_page,
    require_role_page,
    normalize_identifier,
    verify_elevenlabs_signature,
)
from admin_service import AdminService
from admin_seed import ensure_default_admin, ensure_plans
from client_service import ClientService
from billing_service import BillingService
from backup_db import perform_backup, enforce_retention
from stripe_service import StripeService
from queue_utils import get_queue, get_redis_connection
from jobs.email_jobs import send_email_job
from jobs.stripe_jobs import process_stripe_event_job
from jobs.eleven_jobs import process_elevenlabs_event_job
from services.realtime_bridge import RealtimeSession, terminate_session
from services.business_hours import is_open_now
from services.validators import validate_open_hours_schema
from services.call_session import CallSessionManager, CallStatus
from twilio.request_validator import RequestValidator
from twilio.rest import Client as TwilioClient
from alerting import (
    log_critical_error,
    track_webhook_success,
    get_monitoring_stats,
    notify_chat_message,
)

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

# Secrets Management
SECRET_KEY = os.getenv("SECRET_KEY")
if not SECRET_KEY:
    raise RuntimeError("SECRET_KEY is required")

if len(SECRET_KEY) < 32:
    logger.warning("SECRET_KEY is too short (less than 32 chars). Please use a stronger key in production.")

# Twilio Client (for outbound calls / modifications)
TWILIO_ACCOUNT_SID = os.getenv("TWILIO_ACCOUNT_SID")
TWILIO_AUTH_TOKEN = os.getenv("TWILIO_AUTH_TOKEN")
twilio_client = None
if TWILIO_ACCOUNT_SID and TWILIO_AUTH_TOKEN:
    try:
        twilio_client = TwilioClient(TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN)
    except Exception as e:
        logger.error(f"Failed to initialize Twilio Client: {e}")


async def validate_twilio_signature(request: Request) -> bool:
    auth_token = os.getenv("TWILIO_AUTH_TOKEN")
    if not auth_token:
        logger.error("TWILIO_AUTH_TOKEN not set; rejecting Twilio webhook.")
        return False

    signature = request.headers.get("X-Twilio-Signature", "")
    url = str(request.url)
    validator = RequestValidator(auth_token)

    if request.method in ("POST", "PUT", "PATCH"):
        content_type = request.headers.get("content-type", "")
        if "application/x-www-form-urlencoded" in content_type or "multipart/form-data" in content_type:
            form_data = await request.form()
            params = {k: v for k, v in form_data.items()}
            return validator.validate(url, params, signature)

        body = await request.body()
        body_str = body.decode("utf-8") if isinstance(body, (bytes, bytearray)) else str(body)
        return validator.validate(url, body_str, signature)

    params = dict(request.query_params)
    return validator.validate(url, params, signature)

app = FastAPI()
app.add_middleware(
    SessionMiddleware,
    secret_key=SECRET_KEY,
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

@app.exception_handler(NotAuthenticatedPage)
async def not_authenticated_handler(request: Request, exc: NotAuthenticatedPage):
    return RedirectResponse(url="/login", status_code=302)

@app.exception_handler(NotAuthorizedPage)
async def not_authorized_handler(request: Request, exc: NotAuthorizedPage):
    # Smart redirect based on role
    if exc.required_role == "admin" and exc.user.role == "client":
        return RedirectResponse(url="/dashboard", status_code=302)
    elif exc.required_role == "client" and exc.user.role == "admin":
        return RedirectResponse(url="/dashboard", status_code=302)

    # Fallback
    return RedirectResponse(url="/", status_code=302)


@app.on_event("startup")
async def startup_event():
    """
    Run database backup and retention policy on application startup.
    """
    ensure_default_admin()
    ensure_plans()

    # Log DB Connection (Safe)
    db_url = os.getenv("DATABASE_URL", "sqlite:///./app.db")
    if "@" in db_url:
        # Sanitize credentials: postgresql://user:pass@host/db -> postgresql://...:***@host/db
        try:
            prefix = db_url.split("://")[0]
            rest = db_url.split("@")[1]
            logger.info(f"DATABASE_URL configured: {prefix}://***:***@{rest}")
        except:
            logger.info("DATABASE_URL configured (masked)")
    else:
        logger.info(f"DATABASE_URL configured: {db_url}")

    # Log Current DB Revision
    try:
        # Avoid circular import or complex dependency if possible, but we need DB session
        with SessionLocal() as db:
            result = db.execute(text("SELECT version_num FROM alembic_version"))
            row = result.fetchone()
            rev = row[0] if row else "unknown"
            logger.info(f"DB Schema Revision: {rev}")
    except Exception as e:
        logger.warning(f"Could not read alembic_version: {e}")

    # Log ADMIN_EMAIL status
    admin_email_configured = "yes" if os.getenv("ADMIN_EMAIL") else "no"
    logger.info(f"ADMIN_EMAIL configured: {admin_email_configured}")

    # Log TELEGRAM status
    telegram_configured = "yes" if os.getenv("TELEGRAM_BOT_TOKEN") and os.getenv("TELEGRAM_ADMIN_CHAT_ID") else "no"
    logger.info(f"TELEGRAM ALERT configured: {telegram_configured}")

    try:
        logger.info("Starting database backup...")
        perform_backup()
        enforce_retention()
        logger.info("Database backup and retention policy enforcement completed.")
    except Exception as e:
        logger.error(f"Error during database backup on startup: {e}")

# Nome della TUA agency / servizio, non del singolo studio
STUDIO_NAME = os.getenv("STUDIO_NAME", "Mr.Automa")

# Email mittente (la tua)
EMAIL_FROM = os.getenv("EMAIL_FROM")  # es: "Mr.Automa <edo.buffa9898@gmail.com>"
ELEVEN_API_KEY = os.getenv("ELEVEN_API_KEY")
SMTP_HOST = os.getenv("SMTP_HOST", "smtp.gmail.com")
SMTP_PORT = int(os.getenv("SMTP_PORT", "587"))
SMTP_USER = os.getenv("SMTP_USER")
SMTP_PASSWORD = os.getenv("SMTP_PASSWORD")
LOGS_DIR = Path("logs")
LOGS_DIR.mkdir(exist_ok=True)
LEADS_LOG_DIR = LOGS_DIR / "leads"
LEADS_LOG_DIR.mkdir(exist_ok=True)
LEADS_LOG_FILE = LEADS_LOG_DIR / "leads.jsonl"
LEAD_RATE_LIMIT = {"window_seconds": 600, "max_requests": 5}
LEAD_REQUEST_LOG: Dict[str, List[float]] = {}

ALLOWED_LEAD_SECTORS = {
    "Studio professionale",
    "Sanità",
    "Agenzia",
    "E-commerce",
    "Artigiano",
    "Servizi B2B",
    "Altro",
}
ALLOWED_LEAD_VOLUMES = {"0–20/mese", "20–100", "100–300", "300+"}

def get_public_base_url(request: Optional[Request] = None) -> str:
    """
    Returns the public base URL of the application.
    Prioritizes DOMAIN_NAME env var (e.g. 'https://myapp.com').
    Falls back to request.base_url if available.
    Defaults to localhost.
    """
    domain = os.getenv("DOMAIN_NAME")
    if domain:
        # Ensure scheme
        if not domain.startswith("http"):
            domain = f"https://{domain}"
        return domain.rstrip("/")

    if request:
        return str(request.base_url).rstrip("/")

    return os.getenv("PUBLIC_BASE_URL") or "http://127.0.0.1:8000"

# Display configuration for plans (prices are not in DB yet)
PLANS_DISPLAY = {
    "starter": {"name": "Starter", "description": "Per chi inizia."},
    "pro": {"name": "Pro", "description": "Il più scelto dai professionisti."},
    "business": {"name": "Business", "description": "Per aziende strutturate."},
}

def get_plans_context(db: Session) -> Dict[str, Any]:
    """
    Fetches plans from DB and merges with display configuration.
    Returns a dictionary keyed by plan code (e.g. 'starter', 'pro').
    """
    # 1. Fetch static/DB data
    plans_db = db.query(Plan).filter(Plan.is_active == True).all()

    # 2. Fetch dynamic prices from Stripe (cached)
    stripe_service = StripeService(db)
    prices = stripe_service.get_stripe_prices()

    plans_ctx = {}
    for p in plans_db:
        if p.code in PLANS_DISPLAY:
            # Merge: Display Config + DB Minutes + Stripe Price
            price_info = prices.get(p.code, {"price_display": "—"})

            interval = price_info.get("interval", "month")
            interval_map = {"month": "/mese", "year": "/anno", "week": "/settimana", "day": "/giorno"}
            interval_display = interval_map.get(interval, f"/{interval}") if price_info.get("price_display") != "—" else ""

            plans_ctx[p.code] = {
                **PLANS_DISPLAY[p.code],
                "minutes": p.minutes_per_cycle,
                "code": p.code,
                "price_display": price_info.get("price_display", "—"),
                "interval": interval,
                "interval_display": interval_display
            }
    return plans_ctx

class AgentSettingsUpdate(BaseModel):
    greeting: str | None = None
    notes: str | None = None
    agent_phone_number_id: str | None = None
    test_phone_number: str | None = None

# ================== HEALTH ENDPOINTS ==================

@app.get("/health")
async def health_check(db: Session = Depends(get_db)):
    """
    Extended Health Check for monitoring and diagnostics.
    Returns:
    {
      "status": "ok"|"degraded"|"error",
      "db": true|false,
      "redis": true|false,
      "pending_jobs": int,
      "last_webhook": "ISO8601",
      "last_email_sent": "ISO8601"
    }
    """
    response_data = {
        "status": "ok",
        "db": False,
        "redis": False,
        "pending_jobs": 0,
        "last_webhook": None,
        "last_email_sent": None
    }

    # 1. DB Check
    try:
        db.execute(text("SELECT 1"))
        response_data["db"] = True
    except Exception as e:
        logger.error(f"Health check DB failed: {e}")
        response_data["db"] = False

    # 2. Redis & Queue Check
    try:
        redis_conn = get_redis_connection()
        redis_conn.ping()
        response_data["redis"] = True

        # Pending Jobs
        try:
            queue = get_queue()
            response_data["pending_jobs"] = queue.count
        except Exception as q_e:
            logger.warning(f"Health check Queue count failed: {q_e}")
            # If redis is up but queue fails, we keep redis=True but job count might be off
            response_data["pending_jobs"] = 0

    except Exception as e:
        logger.error(f"Health check Redis failed: {e}")
        response_data["redis"] = False

    # 3. Retrieve Stats (Last Webhook / Email)
    try:
        stats = get_monitoring_stats()
        response_data["last_webhook"] = stats.get("last_webhook_time")
        response_data["last_email_sent"] = stats.get("last_email_time")
    except Exception as e:
        logger.warning(f"Health check stats retrieval failed: {e}")

    # 4. Determine Overall Status
    if not response_data["db"]:
        response_data["status"] = "error" # Critical
    elif not response_data["redis"]:
        response_data["status"] = "degraded" # Semi-critical
    else:
        response_data["status"] = "ok"

    return response_data


# ================== ENDPOINT DI TEST ==================

@app.get("/", response_class=HTMLResponse)
async def root(request: Request, db: Session = Depends(get_db)):
    user = request.session.get("user")
    plans = get_plans_context(db)
    return templates.TemplateResponse("index.html", {"request": request, "user": user, "plans": plans})


# ================== ADMIN ENDPOINTS ==================

@app.get("/admin/clients", response_class=HTMLResponse)
async def admin_get_clients(request: Request, db: Session = Depends(get_db), admin: User = Depends(get_current_admin_user_page)):
    service = AdminService(db)
    clients = service.get_clients()
    return templates.TemplateResponse("admin_clients.html", {"request": request, "clients": clients})

@app.post("/admin/clients/create")
async def admin_create_client(username: str = Form(...), email: str = Form(...), password: str = Form(...), studio_name: str = Form(...), db: Session = Depends(get_db), admin: User = Depends(get_current_admin_user)):
    service = AdminService(db)
    try:
        client = service.create_client(username, email, password, studio_name)
        return {"status": "ok", "client_id": client.id}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

@app.post("/admin/agents/create")
async def admin_create_agent(agent_id: str = Form(...), display_name: str = Form(...), phone_number_id: str = Form(None), db: Session = Depends(get_db), admin: User = Depends(get_current_admin_user)):
    service = AdminService(db)
    try:
        agent = service.create_agent(agent_id, display_name, phone_number_id)
        return {"status": "ok", "agent_id": agent.id}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

@app.post("/admin/clients/{user_id}/assign-agent")
async def admin_assign_agent(user_id: int, agent_id: int = Form(...), db: Session = Depends(get_db), admin: User = Depends(get_current_admin_user)):
    service = AdminService(db)
    try:
        client = service.assign_agent_to_client(user_id, agent_id)
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

@app.get("/admin/phone-numbers", response_class=HTMLResponse)
async def admin_get_phone_numbers(request: Request, db: Session = Depends(get_db), admin: User = Depends(get_current_admin_user_page)):
    service = AdminService(db)
    numbers = service.get_all_phone_numbers()
    return templates.TemplateResponse("admin_phonenumbers.html", {"request": request, "numbers": numbers})

# === API Phone Numbers ===

class CreatePhoneNumberRequest(BaseModel):
    e164: str
    user_id: int
    notes: Optional[str] = None
    office_phone_e164: Optional[str] = None
    timezone: Optional[str] = "Europe/Rome"
    open_hours_json: Optional[Dict[str, Any]] = None

class UpdatePhoneNumberRequest(BaseModel):
    notes: Optional[str] = None
    office_phone_e164: Optional[str] = None
    timezone: Optional[str] = None
    open_hours_json: Optional[Dict[str, Any]] = None

@app.get("/api/admin/phone-numbers")
async def api_admin_get_phone_numbers(
    db: Session = Depends(get_db),
    admin: User = Depends(get_current_admin_user)
):
    service = AdminService(db)
    numbers = service.get_all_phone_numbers()
    items = []
    for n in numbers:
        items.append({
            "id": n.id,
            "e164": n.e164,
            "user_id": n.user_id,
            "username": n.user.username if n.user else None,
            "status": n.status,
            "created_at": n.created_at.isoformat() if n.created_at else None,
            "released_at": n.released_at.isoformat() if n.released_at else None,
            "notes": n.notes,
            "office_phone_e164": n.office_phone_e164,
            "timezone": n.timezone,
            "open_hours_json": n.open_hours_json
        })
    return {
        "status": "ok",
        "items": items
    }

@app.post("/api/admin/phone-numbers")
async def api_admin_create_phone_number(
    payload: CreatePhoneNumberRequest,
    db: Session = Depends(get_db),
    admin: User = Depends(get_current_admin_user)
):
    # Check for duplicate
    existing = db.query(PhoneNumber).filter(PhoneNumber.e164 == payload.e164).first()
    if existing:
        raise HTTPException(status_code=400, detail="Il numero è già presente nel sistema.")

    # Validate Timezone
    if payload.timezone:
        if payload.timezone not in pytz.all_timezones:
             raise HTTPException(status_code=400, detail="Timezone non valida.")

    # Validate Open Hours Schema
    if payload.open_hours_json:
        if not validate_open_hours_schema(payload.open_hours_json):
             raise HTTPException(status_code=400, detail="Formato orari non valido.")

    service = AdminService(db)
    try:
        phone = service.create_phone_number(payload.e164, payload.user_id)

        # Apply optional fields
        if payload.notes:
            phone.notes = payload.notes

        if payload.office_phone_e164:
            phone.office_phone_e164 = normalize_phone_e164(payload.office_phone_e164)

        if payload.timezone:
            phone.timezone = payload.timezone

        if payload.open_hours_json:
            phone.open_hours_json = payload.open_hours_json

        db.commit()

        return {"status": "ok", "id": phone.id, "e164": phone.e164}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

@app.patch("/api/admin/phone-numbers/{phone_id}")
async def api_admin_update_phone_number(
    phone_id: int,
    payload: UpdatePhoneNumberRequest,
    db: Session = Depends(get_db),
    admin: User = Depends(get_current_admin_user)
):
    phone = db.query(PhoneNumber).filter(PhoneNumber.id == phone_id).first()
    if not phone:
        raise HTTPException(status_code=404, detail="Number not found")

    # Validate Timezone
    if payload.timezone:
        if payload.timezone not in pytz.all_timezones:
             raise HTTPException(status_code=400, detail="Timezone non valida.")

    # Validate Open Hours Schema
    if payload.open_hours_json is not None:
        if not validate_open_hours_schema(payload.open_hours_json):
             raise HTTPException(status_code=400, detail="Formato orari non valido.")

    if payload.notes is not None:
        phone.notes = payload.notes

    if payload.office_phone_e164 is not None:
        if payload.office_phone_e164 == "":
             phone.office_phone_e164 = None
        else:
             phone.office_phone_e164 = normalize_phone_e164(payload.office_phone_e164)

    if payload.timezone is not None:
        phone.timezone = payload.timezone

    if payload.open_hours_json is not None:
        phone.open_hours_json = payload.open_hours_json

    db.commit()
    return {"status": "ok"}

@app.delete("/api/admin/phone-numbers/{phone_id}")
async def api_admin_delete_phone_number(
    phone_id: int,
    db: Session = Depends(get_db),
    admin: User = Depends(get_current_admin_user)
):
    service = AdminService(db)
    try:
        service.mark_phone_number_released(phone_id)
        return {"status": "ok"}
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))

class ReactivatePhoneNumberRequest(BaseModel):
    user_id: int

@app.post("/api/admin/phone-numbers/{phone_id}/reactivate")
async def api_admin_reactivate_phone_number(
    phone_id: int,
    payload: ReactivatePhoneNumberRequest,
    db: Session = Depends(get_db),
    admin: User = Depends(get_current_admin_user)
):
    service = AdminService(db)
    try:
        service.reactivate_phone_number(phone_id, payload.user_id, admin.username)
        return {"status": "ok"}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

@app.delete("/api/admin/phone-numbers/{phone_id}/permanent")
async def api_admin_delete_phone_number_permanent(
    phone_id: int,
    db: Session = Depends(get_db),
    admin: User = Depends(get_current_admin_user)
):
    service = AdminService(db)
    try:
        service.delete_phone_number_permanent(phone_id, admin.username)
        logger.info(f"Admin {admin.username} deleted number ID {phone_id}")
        return {"status": "ok"}
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))

@app.post("/api/admin/phone-numbers/{phone_id}/cancel-deprovision")
async def api_admin_cancel_deprovision(
    phone_id: int,
    db: Session = Depends(get_db),
    admin: User = Depends(get_current_admin_user)
):
    service = AdminService(db)
    try:
        service.cancel_phone_number_deprovisioning(phone_id)
        return {"status": "ok"}
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))

# === API Agent Routing ===

class AgentRoutingCreate(BaseModel):
    user_id: Optional[int] = None
    agent_id: str
    phone_number_id: Optional[int] = None
    is_active: bool = True
    status: str = "active"

class AgentRoutingUpdate(BaseModel):
    user_id: Optional[int] = None
    agent_id: Optional[str] = None
    phone_number_id: Optional[int] = None
    is_active: Optional[bool] = None
    status: Optional[str] = None

@app.get("/api/admin/routing")
async def api_admin_get_routing(
    db: Session = Depends(get_db),
    admin: User = Depends(get_current_admin_user)
):
    routings = db.query(AgentRouting).all()
    items = []
    for r in routings:
        items.append({
            "id": r.id,
            "user_id": r.user_id,
            "username": r.user.username if r.user else "Unknown",
            "agent_id": r.agent_id,
            "phone_number_id": r.phone_number_id,
            "e164": r.phone_number.e164 if r.phone_number else "Unknown",
            "status": r.status,
            "is_active": r.is_active,
            "created_at": r.created_at.isoformat() if r.created_at else None,
            "last_event_at": r.last_event_at.isoformat() if r.last_event_at else None
        })
    return {"status": "ok", "items": items}

@app.post("/api/admin/routing")
async def api_admin_create_routing(
    payload: AgentRoutingCreate,
    db: Session = Depends(get_db),
    admin: User = Depends(get_current_admin_user)
):
    # Verify user exists if provided
    if payload.user_id:
        user = db.query(User).filter(User.id == payload.user_id).first()
        if not user:
            raise HTTPException(status_code=400, detail="User not found")

    # Verify phone exists if provided
    if payload.phone_number_id:
        phone = db.query(PhoneNumber).filter(PhoneNumber.id == payload.phone_number_id).first()
        if not phone:
            raise HTTPException(status_code=400, detail="Phone number not found")

        # Validation: Must be active
        if phone.status != 'active' or phone.released_at is not None:
             logger.warning(f"Admin attempted to bind inactive phone {phone.id} to routing")
             raise HTTPException(status_code=400, detail="Il numero deve essere attivo per essere assegnato.")

    new_routing = AgentRouting(
        user_id=payload.user_id,
        agent_id=payload.agent_id,
        phone_number_id=payload.phone_number_id,
        is_active=payload.is_active,
        status=payload.status
    )
    db.add(new_routing)
    db.commit()
    db.refresh(new_routing)

    return {"status": "ok", "id": new_routing.id}

@app.patch("/api/admin/routing/{routing_id}")
async def api_admin_update_routing(
    routing_id: int,
    payload: AgentRoutingUpdate,
    db: Session = Depends(get_db),
    admin: User = Depends(get_current_admin_user)
):
    routing = db.query(AgentRouting).filter(AgentRouting.id == routing_id).first()
    if not routing:
        raise HTTPException(status_code=404, detail="Routing not found")

    if payload.user_id is not None:
        if payload.user_id == 0: # convention to unassign
             routing.user_id = None
        else:
             user = db.query(User).filter(User.id == payload.user_id).first()
             if not user:
                 raise HTTPException(status_code=400, detail="User not found")
             routing.user_id = payload.user_id

    if payload.agent_id is not None:
        routing.agent_id = payload.agent_id
    if payload.phone_number_id is not None:
        phone = db.query(PhoneNumber).filter(PhoneNumber.id == payload.phone_number_id).first()
        if not phone:
             raise HTTPException(status_code=400, detail="Phone number not found")
        routing.phone_number_id = payload.phone_number_id
    if payload.is_active is not None:
        routing.is_active = payload.is_active
    if payload.status is not None:
        routing.status = payload.status

    db.commit()
    return {"status": "ok"}

@app.delete("/api/admin/routing/{routing_id}")
async def api_admin_delete_routing(
    routing_id: int,
    db: Session = Depends(get_db),
    admin: User = Depends(get_current_admin_user)
):
    routing = db.query(AgentRouting).filter(AgentRouting.id == routing_id).first()
    if not routing:
        raise HTTPException(status_code=404, detail="Routing not found")

    db.delete(routing)
    db.commit()
    return {"status": "ok"}

@app.get("/api/admin/unassigned-events")
async def api_admin_get_unassigned_events(
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
    admin: User = Depends(get_current_admin_user)
):
    query = db.query(UnassignedEvent).order_by(UnassignedEvent.created_at.desc())
    total = query.count()
    events = query.offset(offset).limit(limit).all()

    items = []
    for e in events:
        items.append({
            "id": e.id,
            "agent_id": e.agent_id,
            "phone_number": e.phone_number,
            "payload": e.payload,
            "created_at": e.created_at.isoformat() if e.created_at else None
        })

    return {"status": "ok", "total": total, "items": items}

# Legacy endpoints (kept for compatibility)
@app.post("/admin/phone-numbers/create")
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
async def admin_cancel_deprovision_legacy(phone_id: int, db: Session = Depends(get_db), admin: User = Depends(get_current_admin_user)):
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


@app.get("/admin/diagnostics", response_class=HTMLResponse)
async def admin_diagnostics(
    request: Request,
    db: Session = Depends(get_db),
    admin: User = Depends(get_current_admin_user)
):
    # 1. Fetch Monitoring Stats (Redis)
    stats = get_monitoring_stats()

    # 2. Fetch DB Stats (Counts)
    today_start = datetime.combine(date.today(), datetime.min.time())
    events_today = db.query(UsageEvent).filter(UsageEvent.created_at >= today_start).count()

    # 3. Active Agents
    active_routing = db.query(AgentRouting).filter(AgentRouting.status == 'active').all()
    # Enrich with user info and phone number
    agents_list = []
    for r in active_routing:
        username = r.user.username if r.user else "Unassigned"
        phone = r.phone_number.e164 if r.phone_number else "N/D"
        agents_list.append({
            "agent_id": r.agent_id,
            "username": username,
            "phone": phone
        })

    # 4. Status Checks (Live)
    db_status = True
    try:
        db.execute(text("SELECT 1"))
    except:
        db_status = False

    redis_status = True
    queue_count = 0
    try:
        r = get_redis_connection()
        r.ping()
        q = get_queue()
        queue_count = q.count
    except:
        redis_status = False

    context = {
        "request": request,
        "user": admin,
        "stats": stats,
        "events_today": events_today,
        "agents": agents_list,
        "db_status": db_status,
        "redis_status": redis_status,
        "queue_count": queue_count
    }

    return templates.TemplateResponse("admin_diagnostics.html", context)

@app.get("/admin/export/minutes")
async def admin_export_minutes(
    from_date: str = Query(..., alias="from"),
    to_date: str = Query(..., alias="to"),
    db: Session = Depends(get_db),
    admin: User = Depends(get_current_admin_user_page)
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
    admin: User = Depends(get_current_admin_user_page)
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


@app.get("/billing/plans", response_class=HTMLResponse)
async def billing_plans(request: Request, db: Session = Depends(get_db)):
    user = request.session.get("user")
    plans = get_plans_context(db)
    return templates.TemplateResponse("plans.html", {"request": request, "user": user, "plans": plans})


@app.post("/billing/checkout")
async def create_checkout_session(
    plan_code: str = Body(..., embed=True),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    service = StripeService(db)
    try:
        # Assuming we have a configured base URL or use request headers
        base_url = get_public_base_url()
        base_url = base_url.rstrip("/")

        success_url = f"{base_url}/dashboard?billing=success"
        cancel_url = f"{base_url}/?billing=cancel"

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


# ================== WEBHOOK TWILIO ==================

@app.post("/twilio/authorize")
async def twilio_authorize(
    request: Request,
    To: str = Form(...),
    From: str = Form(...),
    CallSid: str = Form(...),
    db: Session = Depends(get_db)
):
    """
    Authorize incoming Twilio calls.
    Returns: { "allowed": true } or { "allowed": false, "reason": "..." }
    """
    if not await validate_twilio_signature(request):
        logger.warning(f"Invalid Twilio Signature for authorize {CallSid}")
        return Response(status_code=403, content="Invalid Signature")

    # Normalize To (remove spaces)
    normalized_to = To.replace(" ", "").strip()

    # 1. Lookup Phone Number
    phone = db.query(PhoneNumber).filter(PhoneNumber.e164 == normalized_to).first()
    if not phone:
        return {"allowed": False, "reason": "Number not found"}

    # 2. Get User
    user = phone.user
    if not user:
        return {"allowed": False, "reason": "User not found"}

    # 3. Check User Active
    if not user.is_active:
        return {"allowed": False, "reason": "User suspended"}

    # 4. Check Plan
    if not user.has_active_plan():
        return {"allowed": False, "reason": "No active plan"}

    # 5. Check Agent Routing
    # If a routing exists for this phone number, verify it is active.
    routing = db.query(AgentRouting).filter(AgentRouting.phone_number_id == phone.id).first()
    if routing:
        if not routing.is_active:
            return {"allowed": False, "reason": "Agent disabled"}

    return {"allowed": True}


@app.post("/twilio/voice")
async def twilio_voice(
    request: Request,
    To: str = Form(...),
    From: str = Form(...),
    CallSid: str = Form(...),
    db: Session = Depends(get_db)
):
    """
    Twilio Voice Webhook (TwiML).
    Looks up the agent associated with the called number (To) and connects via WebSocket.
    Enforces Twilio Signature validation.
    """
    # 0. Signature Validation
    if not await validate_twilio_signature(request):
        logger.warning(f"Invalid Twilio Signature for call {CallSid}")
        return Response(status_code=403, content="Invalid Signature")

    # Normalize To
    normalized_to = To.replace(" ", "").strip()

    # 1. Lookup Phone
    phone = db.query(PhoneNumber).filter(PhoneNumber.e164 == normalized_to).first()

    allowed = False
    reason = None
    agent_id = None

    if not phone:
        reason = "Number not found"
    else:
        user = phone.user
        if not user:
            reason = "User not found"
        elif not user.is_active:
            reason = "User suspended"
        elif not user.has_active_plan():
            reason = "No active plan"
        else:
            # Check Routing
            routing = db.query(AgentRouting).filter(
                AgentRouting.phone_number_id == phone.id,
                AgentRouting.is_active == True
            ).first()
            if routing:
                agent_id = routing.agent_id
                allowed = True
            else:
                reason = "Agent disabled"

    # Log structured info
    logger.info(json.dumps({
        "event": "twilio_voice_webhook",
        "CallSid": CallSid,
        "From": From,
        "To": To,
        "agent_id": agent_id,
        "allowed": allowed,
        "reason": reason
    }))

    # 2. Handle missing/blocked agent
    if not allowed:
        # Fallback or Reject
        message = "Il numero chiamato non è configurato correttamente."
        if reason in ("User suspended", "No active plan"):
             message = "Servizio non attivo. Contattare l'amministrazione."

        xml = f"""
        <Response>
            <Say language="it-IT">{message}</Say>
            <Hangup/>
        </Response>
        """
        return Response(content=xml, media_type="application/xml")

    # 3. Business Logic: Office Forwarding (if allowed)
    is_open = False
    if phone.open_hours_json and phone.timezone:
        is_open = is_open_now(phone.open_hours_json, phone.timezone)

    # If Open AND Office Phone set -> Forward
    if is_open and phone.office_phone_e164:
        logger.info(f"Forwarding call {CallSid} to office {phone.office_phone_e164} (Open in {phone.timezone})")

        # Start Session (Human Requested)
        try:
            CallSessionManager().start_session(
                call_sid=CallSid,
                agent_id=agent_id,
                phone_number_id=phone.id,
                status=CallStatus.HUMAN_REQUESTED,
                office_phone_e164=phone.office_phone_e164,
                user_id=user.id,
                caller_number=From
            )
        except Exception as e:
            logger.error(f"Failed to start call session {CallSid}: {e}")

        # Construct action URL
        base_url = str(request.base_url).rstrip("/")
        action_url = f"{base_url}/twilio/after_dial?agent_id={agent_id}"

        xml = f"""
        <Response>
            <Dial timeout="15" action="{action_url}">
                {phone.office_phone_e164}
            </Dial>
        </Response>
        """
        return Response(content=xml, media_type="application/xml")

    # 4. Fallback: Start AI (Closed or No forwarding)
    # Start Session (AI Active)
    try:
        CallSessionManager().start_session(
            call_sid=CallSid,
            agent_id=agent_id,
            phone_number_id=phone.id,
            status=CallStatus.AI_ACTIVE,
            office_phone_e164=phone.office_phone_e164,
            user_id=user.id,
            caller_number=From
        )
    except Exception as e:
        logger.error(f"Failed to start call session {CallSid}: {e}")

    return _build_ai_connect_twiml(request, agent_id)


def _build_ai_connect_twiml(request: Request, agent_id: str) -> Response:
    # Replace http/https with ws/wss
    base_url = str(request.base_url).rstrip("/")
    if "https" in base_url:
        ws_base = base_url.replace("https://", "wss://")
    else:
        ws_base = base_url.replace("http://", "ws://")

    stream_url = f"{ws_base}/ws/twilio?agent_id={agent_id}"

    xml = f"""
    <Response>
        <Connect>
            <Stream url="{stream_url}">
                 <Parameter name="agent_id" value="{agent_id}" />
            </Stream>
        </Connect>
    </Response>
    """
    return Response(content=xml, media_type="application/xml")


@app.post("/twilio/after_dial")
async def twilio_after_dial(
    request: Request,
    DialCallStatus: str = Form(...),
    CallSid: str = Form(...),
    agent_id: str = Query(...)
):
    """
    Callback after <Dial> completes.
    If 'completed', we hangup.
    If 'busy', 'no-answer', 'failed', 'canceled', we fallback to AI.
    """
    if not await validate_twilio_signature(request):
        logger.warning(f"Invalid Twilio Signature for after_dial {CallSid}")
        return Response(status_code=403, content="Invalid Signature")

    logger.info(f"After Dial: status={DialCallStatus} agent={agent_id}")

    if DialCallStatus == "completed":
        # Update session to connected then ended
        try:
            mgr = CallSessionManager()
            mgr.update_status(CallSid, CallStatus.HUMAN_CONNECTED)
            mgr.end_session(CallSid)
        except Exception as e:
            logger.error(f"Failed to update session {CallSid}: {e}")

        return Response(content="<Response><Hangup/></Response>", media_type="application/xml")

    # Fallback to AI
    try:
        CallSessionManager().update_status(CallSid, CallStatus.AI_ACTIVE)
    except Exception as e:
        logger.error(f"Failed to update session {CallSid}: {e}")

    return _build_ai_connect_twiml(request, agent_id)


@app.websocket("/ws/twilio")
async def websocket_twilio(websocket: WebSocket, agent_id: str = Query(...), db: Session = Depends(get_db)):
    """
    WebSocket endpoint for Twilio Media Streams.
    Bridges the audio stream to ElevenLabs Realtime.
    """
    await websocket.accept()

    # Validate Agent
    routing = db.query(AgentRouting).filter(AgentRouting.agent_id == agent_id, AgentRouting.is_active == True).first()
    if not routing:
        logger.warning(f"WebSocket rejected: Invalid or inactive agent {agent_id}")
        await websocket.close(code=4003) # Forbidden
        return

    session = RealtimeSession(websocket, agent_id)
    await session.start()


@app.post("/calls/{call_sid}/barge-in")
async def calls_barge_in(
    call_sid: str,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    Endpoints to request human barge-in.
    Stops AI, updates status, and redirects call to office number.
    """
    mgr = CallSessionManager()
    session = mgr.get_session(call_sid)

    # 1. Verify Session
    if not session:
        raise HTTPException(status_code=404, detail="Call session not found")

    if session.get("status") != CallStatus.AI_ACTIVE:
        raise HTTPException(status_code=400, detail=f"Call not eligible for barge-in (status: {session.get('status')})")

    agent_id = session.get("agent_id")

    # 2. Authorization
    if current_user.role != "admin":
        # Check if user owns this agent
        # We check if any of the user's agents match the session agent_id
        has_access = any(a.agent_id == agent_id for a in current_user.agents)
        if not has_access:
            # Fallback: Check AgentRouting directly if user_agents might be stale/lazy
            routing = db.query(AgentRouting).filter(
                AgentRouting.agent_id == agent_id,
                AgentRouting.user_id == current_user.id
            ).first()
            if not routing:
                raise HTTPException(status_code=403, detail="Access denied")

    # 3. Update Status
    try:
        mgr.update_status(call_sid, CallStatus.HUMAN_REQUESTED)
    except Exception as e:
        logger.error(f"Barge-in: Failed to update Redis for {call_sid}: {e}")

    # 4. Terminate WebSocket (Stop AI)
    # This disconnects the current Media Stream.
    # We must also concurrently update the call via Twilio API to prevent hangup.
    await terminate_session(call_sid)

    # 5. Redirect Call (Connect Human)
    office_phone = session.get("office_phone_e164")
    if office_phone and twilio_client:
        try:
            base_url = get_public_base_url(request)
            # Redirect to TwiML generator endpoint to ensure late binding state check
            connect_url = f"{base_url}/twilio/barge_in_connect"

            twilio_client.calls(call_sid).update(url=connect_url, method="POST")
            logger.info(f"Barge-in: Redirected {call_sid} to {connect_url}")
        except Exception as e:
            logger.error(f"Barge-in: Twilio redirect failed for {call_sid}: {e}")
            # We don't fail the request because the AI is at least stopped
    else:
        logger.warning(f"Barge-in: No office phone or Twilio client configured for {call_sid}")

    return {
        "status": "ok",
        "call_status": CallStatus.HUMAN_REQUESTED,
        "office_phone": office_phone
    }

@app.post("/twilio/barge_in_connect")
async def twilio_barge_in_connect(
    request: Request,
    CallSid: str = Form(...)
):
    """
    TwiML endpoint for barge-in connection.
    Verifies that the human was actually requested before dialing.
    """
    if not await validate_twilio_signature(request):
        logger.warning(f"Invalid Twilio Signature for barge-in connect {CallSid}")
        return Response(status_code=403, content="Invalid Signature")

    mgr = CallSessionManager()
    session = mgr.get_session(CallSid)

    if not session:
        logger.warning(f"Barge-in connect: Session not found for {CallSid}")
        return Response(content="<Response><Hangup/></Response>", media_type="application/xml")

    # Verify State
    if session.get("status") != CallStatus.HUMAN_REQUESTED:
        logger.warning(f"Barge-in connect: Invalid status {session.get('status')} for {CallSid}")
        return Response(content="<Response><Hangup/></Response>", media_type="application/xml")

    office_phone = session.get("office_phone_e164")
    agent_id = session.get("agent_id")

    if not office_phone:
        logger.error(f"Barge-in connect: No office phone for {CallSid}")
        return Response(content="<Response><Hangup/></Response>", media_type="application/xml")

    # Update State
    try:
        mgr.update_status(CallSid, CallStatus.HUMAN_CONNECTED)
    except Exception as e:
        logger.error(f"Barge-in connect: Failed to update status for {CallSid}: {e}")

    # Log
    logger.info(f"Barge-in connect: Connecting {CallSid} to {office_phone}")

    # Build TwiML
    base_url = str(request.base_url).rstrip("/")
    action_url = f"{base_url}/twilio/after_dial?agent_id={agent_id}"

    xml = f"""
    <Response>
        <Dial timeout="15" action="{action_url}">
            <Number>{office_phone}</Number>
        </Dial>
    </Response>
    """
    return Response(content=xml, media_type="application/xml")


# ================== WEBHOOK ELEVENLABS ==================

@app.post("/elevenlabs/webhook")
async def elevenlabs_webhook(request: Request):
    """
    Webhook ElevenLabs.
    - Single body read
    - Signature verification (alert if fail)
    - Type validation
    - Async processing
    - Monitoring tracking
    """
    # 0) Auth & Body Read
    secret = os.getenv("ELEVENLABS_WEBHOOK_SECRET")
    raw_body = await request.body()

    if secret:
        if not verify_elevenlabs_signature(raw_body, request.headers, secret):
            # ALERTING: Invalid Signature
            log_critical_error("Webhook ElevenLabs - firma non valida!", context={"action": "webhook_signature_check"})
            logger.warning("[WEBHOOK] Invalid signature")
            return Response(status_code=403)

    # 1) Parse
    try:
        payload = json.loads(raw_body.decode("utf-8"))
    except Exception as e:
        logger.error(f"[WEBHOOK] JSON Decode Error: {e}")
        return Response(status_code=400, content="Invalid JSON")

    # 2) Validate Type
    event_type = payload.get("type")
    if event_type != "post_call_transcription":
        # Return 200 to acknowledge receipt but ignore logic
        return {"status": "ignored", "reason": "unsupported type"}

    # 3) Extract Minimal Info for Log
    data = payload.get("data", {})
    agent_id = data.get("agent_id")
    call_id = data.get("metadata", {}).get("phone_call", {}).get("call_sid")

    # --- BLOCKING LOGIC START ---
    if agent_id:
        try:
            with SessionLocal() as db:
                # 1. Check AgentRouting (Enabled/Disabled)
                routing = db.query(AgentRouting).filter(AgentRouting.agent_id == agent_id).first()
                if routing:
                    if not routing.is_active:
                        logger.warning(f"[WEBHOOK] Blocked: Agent {agent_id} is disabled.")
                        return JSONResponse(status_code=403, content={"error": "Piano scaduto o agente disattivato"})

                # 2. Resolve User
                user = None
                if routing and routing.user_id:
                     user = db.query(User).filter(User.id == routing.user_id).first()

                if not user:
                     # Try legacy/direct mapping via Agent table
                     agent_obj = db.query(Agent).filter(Agent.agent_id == agent_id).first()
                     if agent_obj:
                         user = db.query(User).filter(User.agents.contains(agent_obj)).first()

                # 3. Check User Status & Plan
                if user:
                     if not user.is_active:
                          logger.warning(f"[WEBHOOK] Blocked: User {user.username} is suspended.")
                          return JSONResponse(status_code=403, content={"error": "Piano scaduto o agente disattivato"})

                     # Check active plan (Manual or Stripe)
                     if not user.has_active_plan():
                          logger.warning(f"[WEBHOOK] Blocked: User {user.username} has no active plan.")
                          log_critical_error(f"Webhook bloccato per user {user.username} (agent {agent_id}) - nessun piano attivo.")
                          return JSONResponse(status_code=403, content={"error": "Piano scaduto o agente disattivato"})

        except Exception as e:
            # If DB fails, we log but fail safe (block) as per requirements
            logger.error(f"[WEBHOOK] Error checking blocking rules: {e}")
            return JSONResponse(status_code=403, content={"error": "System error during validation"})
    # --- BLOCKING LOGIC END ---

    logger.info(f"[WEBHOOK] Enqueuing event type={event_type} agent={agent_id} call={call_id}")

    # 4) Enqueue
    try:
        queue = get_queue()
        queue.enqueue(process_elevenlabs_event_job, payload)

        # ALERTING: Track Success
        if agent_id and call_id:
            track_webhook_success(agent_id, call_id)

    except Exception as e:
        # ALERTING: Enqueue failure
        log_critical_error(f"Webhook enqueue failed: {e}", context={"agent_id": agent_id, "call_id": call_id})
        logger.error(f"[WEBHOOK] Failed to enqueue: {e}")
        # Return 500 so ElevenLabs retries if our infrastructure is down
        raise HTTPException(status_code=500, detail="Queue unavailable")

    # 5) Return Immediate Success
    return {"status": "ok"}

@app.get("/logs/{agent_id}/list")
async def view_logs_list(
    agent_id: str,
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
    status: str = Query("all"),
    date_from: str = Query(None),
    date_to: str = Query(None),
    q: str = Query(None),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Restituisce i log impaginati e filtrabili per la dashboard.
    RBAC:
    - Admin: può accedere a qualsiasi agent_id
    - Client: può accedere solo ai suoi agent_id
    """
    # RBAC Check
    if current_user.role != "admin":
        # Check ownership
        user = db.query(User).filter(User.id == current_user.id).first()
        user_agents = [a.agent_id for a in user.agents]
        if agent_id not in user_agents:
            raise HTTPException(status_code=403, detail="Access denied to this agent")

    # Delegate to _read_logs which handles filtering/reading
    return _read_logs(db, [agent_id], limit, offset, status, date_from, date_to, q)

@app.get("/logs/{agent_id}")
async def view_logs(agent_id: str, admin: User = Depends(get_current_admin_user)):
    """
    Restituisce lo storico completo (legacy endpoint, o per debug).
    """
    db = SessionLocal()
    try:
        rows = (
            db.query(CallLog)
            .filter(CallLog.agent_id == agent_id)
            .order_by(CallLog.timestamp.desc())
            .all()
        )
        logs = [row.raw_data for row in rows if row.raw_data]
    finally:
        db.close()

    return {
        "status": "ok",
        "count": len(logs),
        "logs": logs
    }


def _calculate_analytics(db: Session, agent_ids: List[str]) -> Dict[str, Any]:
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

    if not agent_ids:
        return {
            "status": "ok",
            "total_calls": 0,
            "by_day": {},
            "by_client": {},
            "calls_today": 0,
            "calls_last_7_days": 0,
            "errors": 0,
            "clients_count": 0,
            "heatmap": heatmap,
            "by_category": {},
            "by_urgency": {},
        }

    logs = (
        db.query(CallLog)
        .filter(CallLog.agent_id.in_(agent_ids))
        .order_by(CallLog.timestamp.asc())
        .all()
    )

    if logs:
        db_agents = {log.agent_id for log in logs}
        for log in logs:
            if not log.timestamp:
                continue

            dt = log.timestamp
            total_calls += 1

            # ---- per giorno ----
            day_str = dt.date().isoformat()
            stats_by_day[day_str] = stats_by_day.get(day_str, 0) + 1

            # ---- per cliente ----
            stats_by_client[log.agent_id] = stats_by_client.get(log.agent_id, 0) + 1

            # ---- oggi / ultimi 7 giorni ----
            d = dt.date()
            if d == today:
                calls_today += 1
            if d >= last_7_start:
                calls_last_7 += 1

            # ---- errori / fallite ----
            inner_data = (log.raw_data or {}).get("data", {})
            status = log.status or inner_data.get("status")

            if status == "failure":
                errors += 1
            elif status == "success":
                pass
            else:
                analysis = inner_data.get("analysis", {})
                call_successful = None
                termination_reason = None
                if isinstance(analysis, dict):
                    call_successful = analysis.get("call_successful")
                    termination_reason = analysis.get("termination_reason")

                if call_successful == "failure" or termination_reason:
                    errors += 1

            # ---- AI enrichment (categoria / urgenza) ----
            ai = (log.raw_data or {}).get("ai_enrichment", {})
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
        "clients_count": len(agent_ids),
        "heatmap": heatmap,
        "by_category": stats_by_category,
        "by_urgency": stats_by_urgency,
    }



@app.get("/analytics/global")
async def analytics_global(
    db: Session = Depends(get_db),
    admin: User = Depends(get_current_admin_user)
):
    """
    Ritorna statistiche aggregate da TUTTI i log.
    """
    agent_ids = [agent.agent_id for agent in db.query(Agent).all()]
    return _calculate_analytics(db, agent_ids)

@app.get("/api/analytics")
async def analytics_user(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Ritorna statistiche aggregate per i log dell'utente corrente.
    """
    user = db.query(User).filter(User.id == current_user.id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    agent_ids = [a.agent_id for a in user.agents]
    return _calculate_analytics(db, agent_ids)


@app.get("/api/client/phone-numbers")
async def api_client_phone_numbers(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Returns phone numbers assigned to the current client.
    Uses PhoneNumber as the source of truth (owned numbers).
    """
    phones = db.query(PhoneNumber).filter(
        PhoneNumber.user_id == current_user.id,
        PhoneNumber.released_at == None
    ).all()

    items = []
    for p in phones:
        # Try to find associated routing info if it exists
        # We look for a routing entry that points to this phone number
        routing = db.query(AgentRouting).filter(AgentRouting.phone_number_id == p.id).first()

        agent_name = "Agente"
        agent_id = "Non assegnato"

        if routing:
            agent_id = routing.agent_id
            agent = db.query(Agent).filter(Agent.agent_id == routing.agent_id).first()
            if agent:
                agent_name = agent.display_name

        items.append({
            "agent_id": agent_id,
            "display_name": agent_name,
            "phone_number": p.e164,
            "notes": p.notes,
            "status": p.status
        })

    return {"status": "ok", "items": items}

@app.get("/api/client/active-call")
async def api_client_active_call(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Returns the current active call for the user, if any.
    """
    mgr = CallSessionManager()
    session = mgr.get_active_call_for_user(current_user.id)

    if not session:
        return {"status": "ok", "active_call": None}

    return {
        "status": "ok",
        "active_call": {
            "call_sid": session.get("call_sid"),
            "status": session.get("status"),
            "office_phone_e164": session.get("office_phone_e164"),
            "caller_number": session.get("caller_number"),
            "agent_id": session.get("agent_id")
        }
    }


class AdminUpdateUserRequest(BaseModel):
    studio_name: Optional[str] = None
    email: Optional[str] = None
    subscription_plan: Optional[str] = None
    plan_expires_at: Optional[str] = None # ISO format or YYYY-MM-DD


def _apply_admin_user_update(user: User, payload: AdminUpdateUserRequest, db: Session) -> None:
    if payload.email is not None:
        if payload.email != user.email:
            existing = db.query(User).filter(User.email == payload.email).first()
            if existing:
                raise HTTPException(status_code=400, detail="Email already in use")
            user.email = payload.email

    if payload.studio_name is not None:
        user.studio_name = payload.studio_name

    if payload.subscription_plan is not None:
        user.subscription_plan = payload.subscription_plan

    if payload.plan_expires_at is not None:
        if payload.plan_expires_at == "":
            user.plan_expires_at = None
        else:
            try:
                # Try full ISO first, then date only
                try:
                    dt = datetime.fromisoformat(payload.plan_expires_at)
                except ValueError:
                    dt = datetime.strptime(payload.plan_expires_at, "%Y-%m-%d")
                    # Set to end of day if just date provided? Or strictly time?
                    # Let's assume midnight or specific time if provided.
                    # If just date, admin probably means "until this date inclusive", so end of day is safer?
                    # Or just keep it simple.
                    dt = dt.replace(hour=23, minute=59, second=59)
                user.plan_expires_at = dt
            except ValueError:
                raise HTTPException(status_code=400, detail="Invalid date format")

@app.get("/admin/users")
async def admin_list_users(
    limit: int = 50,
    offset: int = 0,
    q: Optional[str] = None,
    db: Session = Depends(get_db),
    admin: User = Depends(get_current_admin_user)
):
    query = db.query(User)

    if q:
        query = query.filter(
            (User.email.ilike(f"%{q}%")) |
            (User.username.ilike(f"%{q}%"))
        )

    total = query.count()
    users = query.order_by(User.id.desc()).offset(offset).limit(limit).all()

    items = []
    for u in users:
        # Get latest sub status
        sub = db.query(Subscription).filter(Subscription.user_id == u.id).order_by(Subscription.id.desc()).first()
        sub_status = sub.state if sub else "none"
        plan_code = sub.plan.code if sub and sub.plan else "none"

        items.append({
            "id": u.id,
            "username": u.username,
            "email": u.email,
            "studio_name": u.studio_name,
            "role": u.role,
            "is_active": u.is_active,
            "subscription_status": sub_status,
            "plan_code": plan_code,
            "subscription_plan": u.subscription_plan,
            "plan_expires_at": u.plan_expires_at.strftime("%Y-%m-%d") if u.plan_expires_at else None,
            "created_at": u.created_at.isoformat() if u.created_at else None
        })

    return {"status": "ok", "total": total, "items": items}

@app.patch("/admin/users/{user_id}")
async def admin_update_user(
    user_id: int,
    payload: AdminUpdateUserRequest,
    db: Session = Depends(get_db),
    admin: User = Depends(get_current_admin_user)
):
    """
    Updates user details (email, studio_name).
    """
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    _apply_admin_user_update(user, payload, db)

    db.commit()

    # Audit log
    audit_logger.log_audit_event(
        db=db,
        actor_type="admin",
        action="update_user",
        entity_type="user",
        entity_id=str(user.id),
        admin_username=admin.username,
        meta={"changes": payload.dict(exclude_unset=True)}
    )

    return {"status": "ok", "user": {"id": user.id, "email": user.email, "studio_name": user.studio_name}}


@app.put("/admin/users/{user_id}")
async def admin_put_user(
    user_id: int,
    payload: AdminUpdateUserRequest,
    db: Session = Depends(get_db),
    admin: User = Depends(get_current_admin_user)
):
    """
    Replaces user details (email, studio_name).
    """
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    _apply_admin_user_update(user, payload, db)

    db.commit()

    audit_logger.log_audit_event(
        db=db,
        actor_type="admin",
        action="update_user",
        entity_type="user",
        entity_id=str(user.id),
        admin_username=admin.username,
        meta={"changes": payload.dict(exclude_unset=True)}
    )

    return {"status": "ok", "user": {"id": user.id, "email": user.email, "studio_name": user.studio_name}}

@app.get("/api/admin/agent-users")
async def api_admin_agent_users(
    db: Session = Depends(get_db),
    admin: User = Depends(get_current_admin_user)
):
    """
    Returns a mapping of agent_id -> User details.
    Used by frontend to populate settings dropdown with User info.
    Includes data merged from User and AgentRouting.
    """
    # Fetch all routing entries
    routings = db.query(AgentRouting).all()

    mapping = {}
    for r in routings:
        if r.user_id:
            user = db.query(User).filter(User.id == r.user_id).first()
            if user:
                # We map by agent_id because the frontend selects by agent_id
                mapping[r.agent_id] = {
                    "user_id": user.id,
                    "email": user.email,
                    "studio_name": user.studio_name,
                    "username": user.username,
                    "agent_phone_number_id": r.phone_number_id, # Internal DB ID
                }

    return {"status": "ok", "mapping": mapping}


@app.get("/api/admin/agent-settings/{agent_id}")
async def get_agent_settings(
    agent_id: str,
    db: Session = Depends(get_db),
    admin: User = Depends(get_current_admin_user)
):
    settings = db.query(AgentSettings).filter(AgentSettings.agent_id == agent_id).first()
    if not settings:
        return {
            "status": "ok",
            "settings": {
                "agent_id": agent_id,
                "greeting": "",
                "notes": "",
                "agent_phone_number_id": "",
                "test_phone_number": "",
            },
        }

    return {
        "status": "ok",
        "settings": {
            "agent_id": settings.agent_id,
            "greeting": settings.greeting,
            "notes": settings.notes,
            "agent_phone_number_id": settings.agent_phone_number_id,
            "test_phone_number": settings.test_phone_number,
        },
    }


@app.put("/api/admin/agent-settings/{agent_id}")
async def update_agent_settings(
    agent_id: str,
    payload: AgentSettingsUpdate,
    db: Session = Depends(get_db),
    admin: User = Depends(get_current_admin_user)
):
    settings = db.query(AgentSettings).filter(AgentSettings.agent_id == agent_id).first()
    if not settings:
        settings = AgentSettings(agent_id=agent_id)
        db.add(settings)

    if payload.greeting is not None:
        settings.greeting = payload.greeting
    if payload.notes is not None:
        settings.notes = payload.notes
    if payload.agent_phone_number_id is not None:
        settings.agent_phone_number_id = payload.agent_phone_number_id
    if payload.test_phone_number is not None:
        settings.test_phone_number = payload.test_phone_number

    db.commit()
    db.refresh(settings)

    return {
        "status": "ok",
        "settings": {
            "agent_id": settings.agent_id,
            "greeting": settings.greeting,
            "notes": settings.notes,
            "agent_phone_number_id": settings.agent_phone_number_id,
            "test_phone_number": settings.test_phone_number,
        },
    }

@app.post("/admin/users/{user_id}/suspend")
async def admin_suspend_user(user_id: int, db: Session = Depends(get_db), admin: User = Depends(get_current_admin_user)):
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    user.is_active = False
    db.commit()

    # Audit
    audit_logger.log_audit_event(
        db=db,
        actor_type="admin",
        action="suspend_user",
        entity_type="user",
        entity_id=str(user.id),
        admin_username=admin.username
    )

    return {"status": "ok", "message": f"User {user.username} suspended"}

@app.post("/admin/users/{user_id}/unsuspend")
async def admin_unsuspend_user(user_id: int, db: Session = Depends(get_db), admin: User = Depends(get_current_admin_user)):
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    user.is_active = True
    db.commit()

    # Audit
    audit_logger.log_audit_event(
        db=db,
        actor_type="admin",
        action="unsuspend_user",
        entity_type="user",
        entity_id=str(user.id),
        admin_username=admin.username
    )

    return {"status": "ok", "message": f"User {user.username} unsuspended"}

@app.delete("/admin/users/{user_id}")
async def admin_delete_user(
    user_id: int,
    db: Session = Depends(get_db),
    admin: User = Depends(get_current_admin_user)
):
    # 1. Fetch user
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    # 2. Safety checks
    if user.id == admin.id:
        raise HTTPException(status_code=403, detail="Cannot delete self")

    if user.role == "admin":
        raise HTTPException(status_code=403, detail="Cannot delete other admins")

    try:
        # 3. Transactional deletion of dependencies
        # Delete AgentRouting (depends on User and PhoneNumber)
        db.query(AgentRouting).filter(AgentRouting.user_id == user.id).delete()

        # Delete UsageEvents
        db.query(UsageEvent).filter(UsageEvent.user_id == user.id).delete()

        # Delete PhoneNumbers
        db.query(PhoneNumber).filter(PhoneNumber.user_id == user.id).delete()

        # Delete Subscriptions
        db.query(Subscription).filter(Subscription.user_id == user.id).delete()

        # Delete User
        db.delete(user)

        db.commit()

        # 4. Logging
        logger.info(f"User {user.username} (id={user.id}) deleted by admin {admin.username}")
        audit_logger.log_audit_event(
            db=db,
            actor_type="admin",
            action="delete_user",
            entity_type="user",
            entity_id=str(user_id),
            admin_username=admin.username,
            meta={"deleted_username": user.username}
        )

        return {"status": "ok", "message": f"User {user.username} deleted"}

    except Exception as e:
        db.rollback()
        logger.exception(f"Error deleting user {user_id}")
        raise HTTPException(status_code=500, detail="Database error during deletion")

@app.get("/admin/metrics")
async def admin_metrics(db: Session = Depends(get_db), admin: User = Depends(get_current_admin_user)):
    """
    Returns KPIs for the admin dashboard.
    """
    try:
        # 1. Database Counts
        total_users = db.query(User).filter(User.role == "client").count()
        active_subs = db.query(Subscription).filter(Subscription.state == "active").count()
        churned_subs = db.query(Subscription).filter(Subscription.state == "canceled").count()
        past_due_subs = db.query(Subscription).filter(Subscription.state == "past_due").count()

        # 2. Stripe Payments & Metrics
        stripe_service = StripeService(db)
        recent_payments = stripe_service.get_recent_payments(limit=10)
        stripe_metrics = stripe_service.get_aggregated_metrics()

        # Format payments for UI
        formatted_payments = []
        for p in recent_payments:
            amount_fmt = f"{p['amount']/100:.2f} {p['currency'].upper()}"
            date_fmt = datetime.fromtimestamp(p['created']).strftime("%Y-%m-%d %H:%M")
            email = p.get('billing_details', {}).get('email') or "Unknown"

            formatted_payments.append({
                "email": email,
                "amount": amount_fmt,
                "status": p['status'],
                "date": date_fmt
            })

        return {
            "status": "ok",
            "kpi": {
                "total_users": total_users,
                "active_subscriptions": active_subs,
                "churned": churned_subs,
                "past_due": past_due_subs,
                "mrr": f"€{stripe_metrics['mrr']:.2f}",
                "total_revenue": f"€{stripe_metrics['total_revenue']:.2f}"
            },
            "recent_payments": formatted_payments
        }
    except Exception as e:
        logger.exception("Error fetching admin metrics")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/analytics/{agent_id}")
async def analytics_client(
    agent_id: str,
    db: Session = Depends(get_db),
    admin: User = Depends(get_current_admin_user)
):
    """
    Statistiche temporali solo per un client.
    Grafico linea → chiamate ordinate nel tempo.
    """
    points = [
        row.timestamp.isoformat()
        for row in (
            db.query(CallLog)
            .filter(CallLog.agent_id == agent_id)
            .order_by(CallLog.timestamp.asc())
            .all()
        )
    ]

    points.sort()
    return {
        "status": "ok",
        "points": points
    }



@app.get("/dashboard", response_class=HTMLResponse)
async def dashboard(
    request: Request,
    user: User = Depends(get_current_user_page),
    db: Session = Depends(get_db)
):
    # Logic to fetch subscription
    sub = db.query(Subscription).filter(
        Subscription.user_id == user.id,
        Subscription.state == "active"
    ).first()

    # Manual Plan Check
    manual_plan_active = False
    manual_plan_obj = None
    if not sub and user.has_active_plan():
         # If no active stripe sub, but user has active plan (manual)
         # Verify it is indeed manual (subscription_plan is set)
         if user.subscription_plan and user.subscription_plan != 'NONE':
             manual_plan_active = True
             manual_plan_obj = db.query(Plan).filter(Plan.code == user.subscription_plan).first()

    # Fallback to inactive sub if neither active stripe nor manual found
    if not sub and not manual_plan_active:
        sub = db.query(Subscription).filter(
            Subscription.user_id == user.id
        ).order_by(Subscription.id.desc()).first()

    subscription_data = None
    minutes_limit = 0
    minutes_used = 0
    minutes_remaining = 0
    plan_expires_formatted = None

    if user.plan_expires_at:
        # Italian months mapping
        months = {
            1: "gennaio", 2: "febbraio", 3: "marzo", 4: "aprile", 5: "maggio", 6: "giugno",
            7: "luglio", 8: "agosto", 9: "settembre", 10: "ottobre", 11: "novembre", 12: "dicembre"
        }
        d = user.plan_expires_at
        plan_expires_formatted = f"{d.day} {months[d.month]} {d.year}"

    if sub:
        subscription_data = {
            "state": sub.state,
            "plan_code": sub.plan.code if sub.plan else None,
            "cycle_start": sub.cycle_start.isoformat() if sub.cycle_start else None,
            "cycle_end": sub.cycle_end.isoformat() if sub.cycle_end else None,
            "updated_at": sub.updated_at.isoformat() if sub.updated_at else None,
        }

        if sub.plan:
            minutes_limit = sub.plan.minutes_per_cycle
            # Calculate usage for this subscription
            usage_seconds = db.query(func.sum(UsageEvent.billed_seconds)) \
                                .filter(UsageEvent.subscription_id == sub.id) \
                                .filter(UsageEvent.created_at >= sub.cycle_start) \
                                .filter(UsageEvent.created_at <= sub.cycle_end) \
                                .scalar() or 0
            minutes_used = usage_seconds / 60
            minutes_remaining = max(0, minutes_limit - minutes_used)

    elif manual_plan_active and manual_plan_obj:
        # Construct virtual subscription data for manual plan
        cycle_end_dt = user.plan_expires_at if user.plan_expires_at else datetime.utcnow() + timedelta(days=30)
        cycle_start_dt = cycle_end_dt - timedelta(days=30) # Virtual cycle window

        subscription_data = {
            "state": "active",
            "plan_code": manual_plan_obj.code,
            "cycle_start": cycle_start_dt.isoformat(),
            "cycle_end": cycle_end_dt.isoformat(),
            "updated_at": datetime.utcnow().isoformat(),
            "is_manual": True
        }

        minutes_limit = manual_plan_obj.minutes_per_cycle

        # Calculate usage based on user_id and virtual cycle (since no sub id)
        usage_seconds = db.query(func.sum(UsageEvent.billed_seconds)) \
                            .filter(UsageEvent.user_id == user.id) \
                            .filter(UsageEvent.created_at >= cycle_start_dt) \
                            .filter(UsageEvent.created_at <= cycle_end_dt) \
                            .scalar() or 0
        minutes_used = usage_seconds / 60
        minutes_remaining = max(0, minutes_limit - minutes_used)


    # Convert User to dict safe for JSON
    user_dict = {
        "username": user.username,
        "role": user.role,
        "email": user.email,
        "studio_name": user.studio_name,
        "is_active": user.is_active,
        "agent_ids": [a.agent_id for a in user.agents]
    }

    logger.info(f"Rendering dashboard for user {user.username} (role: {user.role})")

    if user.role == 'admin':
        return templates.TemplateResponse("admin_dashboard.html", {
            "request": request,
            "user": user_dict,
            "subscription": subscription_data
        })

    return templates.TemplateResponse("client_dashboard.html", {
        "request": request,
        "user": user_dict,
        "subscription": subscription_data,
        "minutes_limit": minutes_limit,
        "minutes_used": minutes_used,
        "minutes_remaining": minutes_remaining,
        "plan_expires_formatted": plan_expires_formatted
    })


@app.get("/client/dashboard", response_class=HTMLResponse)
async def client_dashboard(request: Request):
    return RedirectResponse(url="/dashboard", status_code=302)


@app.get("/logout")
async def logout(request: Request):
    request.session.clear()
    return RedirectResponse(url="/", status_code=302)


@app.get("/me")
async def read_users_me(current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    try:
        # Fetch fresh user to ensure agents relationship is loaded
        user = db.query(User).filter(User.id == current_user.id).first()
        agent_ids = [a.agent_id for a in user.agents] if user else []

        # Find active subscription (or just the latest one)
        # We prioritize 'active' status. If none active, we take the most recent one.
        subscription_data = None

        # Simple query for active subscription first
        sub = db.query(Subscription).filter(
            Subscription.user_id == current_user.id,
            Subscription.state == "active"
        ).first()

        # Check Manual Plan if no active stripe sub
        manual_plan_active = False
        if not sub and user.has_active_plan():
             if user.subscription_plan and user.subscription_plan != 'NONE':
                 manual_plan_active = True

        if not sub and not manual_plan_active:
            # Fallback to any latest subscription
            # Subscription model does not have created_at, using id instead
            sub = db.query(Subscription).filter(
                Subscription.user_id == current_user.id
            ).order_by(Subscription.id.desc()).first()

        if sub:
            subscription_data = {
                "state": sub.state,
                "plan_code": sub.plan.code if sub.plan else None,
                "cycle_start": sub.cycle_start.isoformat() if sub.cycle_start else None,
                "cycle_end": sub.cycle_end.isoformat() if sub.cycle_end else None,
                "updated_at": sub.updated_at.isoformat() if sub.updated_at else None,
                "stripe_subscription_id": sub.stripe_subscription_id,
                "stripe_price_id": sub.stripe_price_id
            }
        elif manual_plan_active:
             cycle_end_dt = user.plan_expires_at if user.plan_expires_at else datetime.utcnow() + timedelta(days=30)
             cycle_start_dt = cycle_end_dt - timedelta(days=30)
             subscription_data = {
                "state": "active",
                "plan_code": user.subscription_plan,
                "cycle_start": cycle_start_dt.isoformat(),
                "cycle_end": cycle_end_dt.isoformat(),
                "updated_at": datetime.utcnow().isoformat(),
                "is_manual": True
            }

        return {
            "user": {
                "id": current_user.id,
                "username": current_user.username,
                "email": current_user.email,
                "role": current_user.role,
                "studio_name": current_user.studio_name,
                "is_active": current_user.is_active,
                "stripe_customer_id": current_user.stripe_customer_id,
                "agent_ids": agent_ids
            },
            "subscription": subscription_data
        }
    except Exception as e:
        logger.exception("Error in /me endpoint")
        # Return valid user object even if subscription fetch fails
        return {
            "user": {
                "id": current_user.id,
                "username": current_user.username,
                "email": current_user.email,
                "role": current_user.role,
                "studio_name": current_user.studio_name,
                "is_active": current_user.is_active,
                "stripe_customer_id": current_user.stripe_customer_id,
                "agent_ids": []
            },
            "subscription": None
        }


@app.get("/login", response_class=HTMLResponse)
async def login_form(request: Request):
    just_registered = request.query_params.get("registered") == "1"
    login_error = request.query_params.get("error") == "1"
    reset_success = request.query_params.get("reset") == "1"
    return templates.TemplateResponse(
        "login.html",
        {
            "request": request,
            "just_registered": just_registered,
            "login_error": login_error,
            "reset_success": reset_success,
        },
    )


@app.get("/forgot-password", response_class=HTMLResponse)
async def forgot_password_form(request: Request):
    return templates.TemplateResponse("forgot_password.html", {"request": request})


@app.post("/forgot-password", response_class=HTMLResponse)
async def forgot_password_submit(request: Request, email: str = Form(...), db: Session = Depends(get_db)):
    clean_email = normalize_identifier(email)
    user = db.query(User).filter(User.email == clean_email).first()

    # Always return success message to prevent enumeration
    msg = "Se l'email esiste, riceverai un link per il reset della password."

    if user:
        # Generate token
        token_raw = secrets.token_urlsafe(32)
        token_hashed = hash_password(token_raw)

        # Store in DB
        db_token = PasswordResetToken(
            user_id=user.id,
            token_hash=token_hashed,
            expires_at=datetime.utcnow() + timedelta(minutes=30)
        )
        db.add(db_token)
        db.commit()

        # Build Link
        public_url = get_public_base_url(request)
        reset_link = f"{public_url}/reset-password?token={token_raw}&uid={user.id}"

        subject = "Reimposta la tua password"
        body = f"""
        <p>Ciao {user.username},</p>
        <p>Hai richiesto il reset della password.</p>
        <p><a href="{reset_link}">Clicca qui per reimpostare la tua password</a></p>
        <p>Il link scadrà tra 30 minuti ed è utilizzabile una sola volta.</p>
        <p>Se non sei stato tu, ignora questa email.</p>
        """
        try:
            send_email(user.email, subject, "Please view in HTML", html_body=body)
            logger.info(f"Password reset email sent to {clean_email}")
        except Exception as e:
            logger.error(f"Error sending reset email to {clean_email}: {e}")
            msg = "Errore durante l'invio dell'email. Riprova più tardi."

    return templates.TemplateResponse("forgot_password.html", {"request": request, "message": msg})


@app.get("/reset-password", response_class=HTMLResponse)
async def reset_password_form(request: Request, token: str = Query(...), uid: int = Query(...), db: Session = Depends(get_db)):
    # Validate token existence roughly (detailed check on submit or here if strictly needed)
    # We check if active token exists for user
    # Note: We can't verify hash without the raw token, which we have.
    # But for GET, we might just show the form.
    # Security: If we verify here, we prevent spamming.

    user = db.query(User).filter(User.id == uid).first()
    if not user:
         return templates.TemplateResponse("forgot_password.html", {"request": request, "error": "Link non valido."})

    # Find valid tokens for user
    tokens = db.query(PasswordResetToken).filter(
        PasswordResetToken.user_id == uid,
        PasswordResetToken.used_at == None,
        PasswordResetToken.expires_at > datetime.utcnow()
    ).all()

    valid_found = False
    for t in tokens:
        if verify_password(token, t.token_hash):
            valid_found = True
            break

    if not valid_found:
        return templates.TemplateResponse(
            "forgot_password.html",
            {"request": request, "error": "Link scaduto o non valido. Richiedi un nuovo reset."}
        )

    return templates.TemplateResponse("reset_password.html", {"request": request, "token": token, "uid": uid, "email": user.email})


@app.post("/reset-password", response_class=HTMLResponse)
async def reset_password_submit(
    request: Request,
    token: str = Form(...),
    uid: int = Form(...),
    password: str = Form(...),
    password_confirm: str = Form(...),
    db: Session = Depends(get_db)
):
    # Retrieve user first to have context for re-rendering form on validation error
    user = db.query(User).filter(User.id == uid).first()
    if not user:
         return templates.TemplateResponse("forgot_password.html", {"request": request, "error": "Utente non trovato."})

    if len(password) < 8:
         return templates.TemplateResponse(
            "reset_password.html",
            {"request": request, "token": token, "uid": uid, "email": user.email, "error": "La password deve essere di almeno 8 caratteri."}
        )

    if password != password_confirm:
        return templates.TemplateResponse(
            "reset_password.html",
            {"request": request, "token": token, "uid": uid, "email": user.email, "error": "Le password non coincidono."}
        )

    # Verify Token
    tokens = db.query(PasswordResetToken).filter(
        PasswordResetToken.user_id == uid,
        PasswordResetToken.used_at == None,
        PasswordResetToken.expires_at > datetime.utcnow()
    ).all()

    valid_token_record = None
    for t in tokens:
        if verify_password(token, t.token_hash):
            valid_token_record = t
            break

    if not valid_token_record:
        return templates.TemplateResponse(
            "forgot_password.html",
            {"request": request, "error": "Link scaduto o già utilizzato."}
        )

    # Reset
    user.password_hash = hash_password(password)
    valid_token_record.used_at = datetime.utcnow()
    db.commit()

    # Invalidate sessions?
    # Current session is cookie based. We can't invalidate client cookies from here easily without a session table.
    # But since password changed, they can login with new one.

    return RedirectResponse(url="/login?reset=1", status_code=302)


@app.get("/privacy", response_class=HTMLResponse)
async def privacy_policy(request: Request):
    return templates.TemplateResponse(
        "privacy.html",
        {"request": request},
    )


@app.get("/terms", response_class=HTMLResponse)
async def terms_of_service(request: Request):
    return templates.TemplateResponse(
        "terms.html",
        {"request": request},
    )


def _is_valid_email(email: str) -> bool:
    return re.match(r"^[^@\s]+@[^@\s]+\.[^@\s]+$", email) is not None


def _get_client_ip(request: Request) -> str:
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


def _is_valid_phone(phone: str) -> bool:
    return re.match(r"^[0-9+()\\s.-]{6,}$", phone) is not None


def normalize_phone_e164(phone: str) -> str:
    """
    Normalizes phone number to E.164 format.
    Strips spaces, dashes, parentheses. Ensures leading +.
    """
    if not phone:
        return ""
    # Strip spaces, dashes, parentheses
    cleaned = re.sub(r"[\s\-\(\)]", "", phone)
    if not cleaned.startswith("+"):
        cleaned = "+" + cleaned
    return cleaned


def _check_rate_limit(ip_address: str) -> bool:
    now = time.time()
    window_start = now - LEAD_RATE_LIMIT["window_seconds"]
    timestamps = [ts for ts in LEAD_REQUEST_LOG.get(ip_address, []) if ts > window_start]
    if len(timestamps) >= LEAD_RATE_LIMIT["max_requests"]:
        LEAD_REQUEST_LOG[ip_address] = timestamps
        return False
    timestamps.append(now)
    LEAD_REQUEST_LOG[ip_address] = timestamps
    return True


@app.get("/register", response_class=HTMLResponse)
async def register_form(request: Request):
    return templates.TemplateResponse(
        "register.html",
        {
            "request": request,
            "errors": {},
            "form_data": {"username": "", "email": ""},
        },
    )


@app.post("/register", response_class=HTMLResponse)
async def register_submit(
    request: Request,
    username: str = Form(...),
    email: str = Form(...),
    password: str = Form(...),
    password_confirm: str = Form(...),
    db: Session = Depends(get_db),
):
    errors = {}
    # Normalization
    clean_username = normalize_identifier(username)
    clean_email = normalize_identifier(email)

    ip_address = _get_client_ip(request)
    logger.info(f"REGISTER_ATTEMPT: username={clean_username} email={clean_email} ip={ip_address}")

    if not clean_username:
        errors["username"] = "Lo username è obbligatorio."

    if not clean_email or not _is_valid_email(clean_email):
        errors["email"] = "Inserisci un'email valida."

    if len(password) < 8:
        errors["password"] = "La password deve avere almeno 8 caratteri."

    if password != password_confirm:
        errors["password_confirm"] = "Le password non coincidono."

    if clean_username:
        existing_username = db.query(User).filter(User.username == clean_username).first()
        if existing_username:
            errors["username"] = "Questo username è già in uso."

    if clean_email:
        existing_email = db.query(User).filter(User.email == clean_email).first()
        if existing_email:
            errors["email"] = "Questa email è già in uso."

    if errors:
        return templates.TemplateResponse(
            "register.html",
            {
                "request": request,
                "errors": errors,
                "form_data": {"username": clean_username, "email": clean_email},
            },
        )

    new_user = User(
        username=clean_username,
        email=clean_email,
        password_hash=hash_password(password),
        role="client",
        is_active=True,
    )
    try:
        db.add(new_user)
        db.commit()

        # Verify Persistence
        db.expire_all() # Ensure we fetch from DB
        saved_user = db.query(User).filter(User.id == new_user.id).first()
        if saved_user:
             logger.info(f"REGISTER_OK: id={saved_user.id} role={saved_user.role} active={saved_user.is_active}")
             logger.info("REGISTER_DB_VERIFIED")
        else:
             logger.critical(f"REGISTER_FAIL_PERSISTENCE: User {new_user.id} committed but not found.")

    except Exception as exc:
        db.rollback()
        logger.error(f"REGISTER_FAIL: {type(exc).__name__} {exc}")
        errors["form"] = "Errore durante la registrazione. Riprova."
        return templates.TemplateResponse(
            "register.html",
            {
                "request": request,
                "errors": errors,
                "form_data": {"username": clean_username, "email": clean_email},
            },
        )

    return RedirectResponse(url="/login?registered=1", status_code=302)


@app.post("/lead")
async def lead_submit(request: Request, payload: Dict[str, Any] = Body(...)):
    email = str(payload.get("email", "")).strip()
    phone = str(payload.get("phone", "")).strip()
    privacy = payload.get("privacy")
    sector = str(payload.get("sector", "")).strip()
    volume = str(payload.get("volume", "")).strip()

    if not _is_valid_email(email):
        return Response(
            content=json.dumps({"status": "error", "message": "Email non valida."}),
            status_code=400,
            media_type="application/json",
        )

    if not phone or not _is_valid_phone(phone):
        return Response(
            content=json.dumps({"status": "error", "message": "Telefono non valido."}),
            status_code=400,
            media_type="application/json",
        )

    if privacy is not True:
        return Response(
            content=json.dumps({"status": "error", "message": "Consenso privacy obbligatorio."}),
            status_code=400,
            media_type="application/json",
        )

    if sector not in ALLOWED_LEAD_SECTORS:
        return Response(
            content=json.dumps({"status": "error", "message": "Settore non valido."}),
            status_code=400,
            media_type="application/json",
        )

    if volume not in ALLOWED_LEAD_VOLUMES:
        return Response(
            content=json.dumps({"status": "error", "message": "Volume chiamate non valido."}),
            status_code=400,
            media_type="application/json",
        )

    ip_address = _get_client_ip(request)
    if not _check_rate_limit(ip_address):
        return Response(
            content=json.dumps({"status": "error", "message": "Troppe richieste. Riprova più tardi."}),
            status_code=429,
            media_type="application/json",
        )

    lead_entry = {
        "timestamp_utc": datetime.utcnow().isoformat() + "Z",
        "ip": ip_address,
        "user_agent": request.headers.get("user-agent"),
        "referer": request.headers.get("referer"),
        "full_name": str(payload.get("full_name", "")).strip(),
        "email": email,
        "phone": phone,
        "company": str(payload.get("company", "")).strip(),
        "sector": sector,
        "volume": volume,
        "needs": str(payload.get("needs", "")).strip(),
    }

    try:
        with LEADS_LOG_FILE.open("a", encoding="utf-8") as log_file:
            log_file.write(json.dumps(lead_entry, ensure_ascii=False) + "\n")
    except Exception as exc:
        logger.warning("Unable to write lead log: %s", exc)
        return Response(
            content=json.dumps({"status": "error", "message": "Errore interno."}),
            status_code=500,
            media_type="application/json",
        )

    to_email = os.getenv("ADMIN_EMAIL")

    logger.info("Attempting to send lead email")
    if not to_email:
        logger.warning("ADMIN_EMAIL is not configured. Skipping email sending.")
    else:
        subject = "Nuova richiesta prenotazione"
        body = (
            f"<p>Nuovo lead ricevuto:</p>"
            f"<ul>"
            f"<li><strong>Nome:</strong> {lead_entry['full_name']}</li>"
            f"<li><strong>Email:</strong> {lead_entry['email']}</li>"
            f"<li><strong>Telefono:</strong> {lead_entry['phone']}</li>"
            f"<li><strong>Azienda:</strong> {lead_entry['company']}</li>"
            f"<li><strong>Settore:</strong> {lead_entry['sector']}</li>"
            f"<li><strong>Volume chiamate:</strong> {lead_entry['volume']}</li>"
            f"<li><strong>Note:</strong> {lead_entry['needs']}</li>"
            f"</ul>"
        )
        try:
            # Using reply_to for the lead's email
            send_email(
                to_addr=to_email,
                subject=subject,
                body="Nuovo lead ricevuto. Vedi HTML.",
                html_body=body,
                reply_to=lead_entry['email']
            )
            logger.info("Lead email sent successfully")
        except Exception as exc:
            logger.warning("Unable to send lead email: %s", exc)

    return {"status": "ok"}


@app.post("/login")
async def login_submit(
    request: Request,
    username: str = Form(...),
    password: str = Form(...),
    db: Session = Depends(get_db)
):
    normalized_username = normalize_identifier(username)
    logger.info(f"LOGIN_ATTEMPT: username={normalized_username}")

    # Try to find by username OR email (if desired, but currently code assumes username field is username)
    # The form field is 'username' but user might type email.
    # The legacy code: user = db.query(User).filter(User.username == username).first()
    # Let's support both if it's an email format?
    # For now, stick to strictly matching what register did (username=clean_username).

    user = db.query(User).filter(User.username == normalized_username).first()

    # If not found, try email just in case user is confused
    if not user and "@" in normalized_username:
         user = db.query(User).filter(User.email == normalized_username).first()

    if not user:
        logger.warning(f"LOGIN_FAIL_USER_NOT_FOUND: {normalized_username}")
        return RedirectResponse(url="/login?error=1", status_code=302)

    # Allow login even if inactive, so they can see the "Suspended" dashboard
    # if not user.is_active:
    #    logger.warning(f"LOGIN_FAIL_INACTIVE: {normalized_username} id={user.id}")
    #    return RedirectResponse(url="/login?error=1", status_code=302)

    if not verify_password(password, user.password_hash):
        logger.warning(f"LOGIN_FAIL_HASH_MISMATCH: {normalized_username} id={user.id}")
        return RedirectResponse(url="/login?error=1", status_code=302)

    logger.info(f"LOGIN_OK: id={user.id} role={user.role}")

    request.session["user"] = {
        "user_id": user.id,
        "username": user.username,
        "role": user.role,
    }

    if user.role == "admin":
        return RedirectResponse(url="/dashboard", status_code=302)
    return RedirectResponse(url="/client/dashboard", status_code=302)

@app.get("/api/admin/users/debug")
async def admin_debug_users(
    email: Optional[str] = Query(None),
    db: Session = Depends(get_db),
    admin: User = Depends(get_current_admin_user)
):
    if not email:
        return {"error": "Provide email query param"}

    norm_email = normalize_identifier(email)
    user = db.query(User).filter(User.email == norm_email).first()
    if not user:
        return {"status": "not_found", "searched_email": norm_email}

    return {
        "status": "found",
        "id": user.id,
        "username": user.username,
        "email": user.email,
        "role": user.role,
        "is_active": user.is_active,
        "hash_prefix": user.password_hash[:10] if user.password_hash else None
    }


def _read_logs(
    db: Session,
    agent_ids: List[str],
    limit: int = 50,
    offset: int = 0,
    status: str = "all",
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
    q: Optional[str] = None
):
    """
    Helper to read, filter, sort and paginate logs from the database.
    """
    items = []

    df = datetime.fromisoformat(date_from).date() if date_from else None
    dt = datetime.fromisoformat(date_to).date() if date_to else None

    query = db.query(CallLog)
    if agent_ids:
        query = query.filter(CallLog.agent_id.in_(agent_ids))
    if df:
        query = query.filter(CallLog.timestamp >= datetime.combine(df, datetime.min.time()))
    if dt:
        query = query.filter(CallLog.timestamp <= datetime.combine(dt, datetime.max.time()))
    if status in {"success", "failure"}:
        query = query.filter(CallLog.status == status)

    logs = query.order_by(CallLog.timestamp.desc()).all()

    for log in logs:
        raw = log.raw_data or {}
        ts = log.timestamp.isoformat() if log.timestamp else None
        if not ts:
            continue

        data = raw.get("data", {}) or {}
        analysis = data.get("analysis", {}) or {}
        summary = (
            analysis.get("transcript_summary")
            or analysis.get("summary")
            or data.get("summary")
            or ""
        )
        duration = data.get("duration_secs") or data.get("metadata", {}).get("call_duration_secs")
        caller = data.get("caller_number") or data.get("user_id") or "unknown"
        status_value = log.status or data.get("status") or "success"

        item = {
            "timestamp": ts,
            "caller": caller,
            "status": status_value,
            "summary": str(summary).strip(),
            "duration_secs": duration,
            "raw": raw
        }

        if q:
            q_low = q.lower()
            if q_low not in json.dumps(item, ensure_ascii=False).lower():
                continue

        items.append(item)

    total = len(items)
    paginated_items = items[offset:offset + limit]

    return {"status": "ok", "total": total, "items": paginated_items}




@app.get("/api/logs")
async def get_my_logs(
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
    status: str = Query("all"),
    date_from: str = Query(None),
    date_to: str = Query(None),
    q: str = Query(None),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Ritorna i log dell'utente corrente (Client-scoped).
    Recupera gli agent_id associati all'utente.
    """
    # Force reload user to ensure relationships are loaded
    # Actually, current_user from get_current_user might not have relationships loaded depending on how it was queried
    # But lazy loading should work if session is active.
    # However, get_current_user closes session? No, it depends.
    # Let's re-query to be safe or ensure eager loading.

    user = db.query(User).filter(User.id == current_user.id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    agent_ids = [a.agent_id for a in user.agents]

    if not agent_ids:
        return {"status": "ok", "total": 0, "items": []}

    return _read_logs(db, agent_ids, limit, offset, status, date_from, date_to, q)


# ================== CHAT SUPPORT ==================

class ChatMessageCreate(BaseModel):
    message: str
    user_id: Optional[int] = None # Required for Admin sender

@app.get("/api/chat/messages")
async def get_chat_messages(
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
    user_id: Optional[int] = None, # Admin can specify which user thread
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user_page) # Can be client or admin
):
    target_user_id = current_user.id

    # If Admin, allow viewing other users' chats
    if current_user.role == 'admin':
        if user_id:
            target_user_id = user_id
    elif user_id and user_id != current_user.id:
        raise HTTPException(status_code=403, detail="Cannot view other users' chats")

    total = db.query(ChatMessage).filter(ChatMessage.user_id == target_user_id).count()

    messages = (
        db.query(ChatMessage)
        .filter(ChatMessage.user_id == target_user_id)
        .order_by(ChatMessage.created_at.asc()) # History order
        .offset(offset)
        .limit(limit)
        .all()
    )

    return {
        "status": "ok",
        "total": total,
        "items": [
            {
                "id": m.id,
                "sender": m.sender_type, # 'client' | 'admin'
                "message": m.message,
                "created_at": m.created_at.isoformat() if m.created_at else None,
                "read": m.read
            } for m in messages
        ]
    }

@app.post("/api/chat/messages")
async def send_chat_message(
    payload: ChatMessageCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    sender_type = "client"
    target_user_id = current_user.id

    # Admin logic
    if current_user.role == 'admin':
        sender_type = "admin"
        if not payload.user_id:
            raise HTTPException(status_code=400, detail="Admin must specify user_id")
        target_user_id = payload.user_id

    # Create Message
    msg = ChatMessage(
        user_id=target_user_id,
        sender_type=sender_type,
        message=payload.message,
        read=False
    )
    db.add(msg)
    db.commit()
    db.refresh(msg)

    # Notifications
    if sender_type == "client":
        # Notify Admin via Telegram
        user = db.query(User).filter(User.id == target_user_id).first()
        notify_chat_message(user, payload.message)

    return {"status": "ok", "id": msg.id}

@app.post("/api/chat/read")
async def mark_chat_read(
    payload: Dict[str, Any] = Body(...), # {user_id: ...} optional
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    target_user_id = current_user.id
    target_sender_type = "admin" # Client reads admin messages

    if current_user.role == 'admin':
        if not payload.get("user_id"):
             raise HTTPException(status_code=400, detail="Admin must specify user_id")
        target_user_id = payload["user_id"]
        target_sender_type = "client" # Admin reads client messages

    # Update
    db.query(ChatMessage).filter(
        ChatMessage.user_id == target_user_id,
        ChatMessage.sender_type == target_sender_type,
        ChatMessage.read == False
    ).update({"read": True})

    db.commit()
    return {"status": "ok"}

@app.get("/api/admin/chat/conversations")
async def get_admin_conversations(
    db: Session = Depends(get_db),
    admin: User = Depends(get_current_admin_user)
):
    # List distinct user_ids from ChatMessages
    # And count unread messages (sender_type='client', read=False)

    # Simplified logic using python aggregation
    # Fetch all users who have at least one message

    chat_users_ids = db.query(ChatMessage.user_id).distinct().all()
    ids = [r[0] for r in chat_users_ids]

    if not ids:
        return {"status": "ok", "conversations": []}

    users = db.query(User).filter(User.id.in_(ids)).all()

    conversations = []
    for u in users:
        # Get unread count
        unread = db.query(ChatMessage).filter(
            ChatMessage.user_id == u.id,
            ChatMessage.sender_type == 'client',
            ChatMessage.read == False
        ).count()

        # Get last message
        last_msg = db.query(ChatMessage).filter(ChatMessage.user_id == u.id).order_by(ChatMessage.created_at.desc()).first()

        conversations.append({
            "user_id": u.id,
            "username": u.username,
            "studio_name": u.studio_name,
            "email": u.email,
            "unread_count": unread,
            "last_message": last_msg.message[:50] if last_msg else "",
            "last_active": last_msg.created_at.isoformat() if last_msg else None
        })

    # Sort by last_active desc
    conversations.sort(key=lambda x: x['last_active'] or "", reverse=True)

    return {"status": "ok", "conversations": conversations}

@app.get("/api/chat/unread-count")
async def get_unread_count(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    if current_user.role == 'admin':
        # Total unread messages from clients
        count = db.query(ChatMessage).filter(
            ChatMessage.sender_type == 'client',
            ChatMessage.read == False
        ).count()
    else:
        # Unread messages from admin for this client
        count = db.query(ChatMessage).filter(
            ChatMessage.user_id == current_user.id,
            ChatMessage.sender_type == 'admin',
            ChatMessage.read == False
        ).count()

    return {"status": "ok", "count": count}





    # …qui il tuo log_call(entry, agent_id) o simile…
    # …e la parte di email che già hai…
@app.post("/api/admin/agents/{agent_id}/test-call")
async def test_call(agent_id: str, db: Session = Depends(get_db), admin: User = Depends(get_current_admin_user)):
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

    settings = db.query(AgentSettings).filter(AgentSettings.agent_id == agent_id).first()
    if not settings:
        raise HTTPException(status_code=404, detail="Cliente non trovato")

    if not ELEVEN_API_KEY:
        raise HTTPException(status_code=500, detail="ELEVENLABS_API_KEY non configurata")

    # agent_id di ElevenLabs = agent_id delle nostre config (stiamo usando lo stesso)
    eleven_agent_id = agent_id
    phone_id = settings.agent_phone_number_id
    to_number = settings.test_phone_number

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
            logger.error("Test call error: %s %s", resp.status_code, resp.text)
            raise HTTPException(
                status_code=resp.status_code,
                detail=f"Errore ElevenLabs: {resp.text}"
            )

        data = resp.json()
        # es: {'success': True, 'message': '...', 'conversation_id': '...', 'callSid': '...'}
        return {"status": "ok", "elevenlabs_response": data}

    except HTTPException:
        raise
    except (httpx.HTTPError, TimeoutError) as e:
        logger.error("Test call network error: %s", e)
        raise HTTPException(status_code=502, detail="Errore servizio esterno")
    except Exception as e:
        logger.error("Test call exception: %s", e)
        raise HTTPException(status_code=500, detail="Errore interno nella chiamata di test")
