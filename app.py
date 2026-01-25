import os
import json
import uuid
import secrets
import sentry_sdk
import re
from datetime import datetime
from typing import Any, Dict, Optional, List
from pydantic import BaseModel
from fastapi import FastAPI, HTTPException, Request, Body, Query, Response
from fastapi.responses import HTMLResponse, StreamingResponse
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
from models import User, Subscription, Plan, UsageEvent, PhoneNumber, AgentRouting, UnassignedEvent, PasswordResetToken, AgentSettings, CallLog
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
from models import Agent, Subscription
from queue_utils import get_queue, get_redis_connection
from jobs.email_jobs import send_email_job
from jobs.stripe_jobs import process_stripe_event_job
from jobs.eleven_jobs import process_elevenlabs_event_job
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

class UpdatePhoneNumberRequest(BaseModel):
    notes: Optional[str] = None

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
            "notes": n.notes
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
    service = AdminService(db)
    try:
        phone = service.create_phone_number(payload.e164, payload.user_id)
        if payload.notes:
            phone.notes = payload.notes
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

    if payload.notes is not None:
        phone.notes = payload.notes

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


# ================== WEBHOOK ELEVENLABS ==================

@app.post("/elevenlabs/webhook")
async def elevenlabs_webhook(request: Request):
    """
    Webhook ElevenLabs.
    - Single body read
    - Signature verification
    - Type validation
    - Async processing
    """
    # 0) Auth & Body Read
    secret = os.getenv("ELEVENLABS_WEBHOOK_SECRET")
    raw_body = await request.body()

    if secret:
        if not verify_elevenlabs_signature(raw_body, request.headers, secret):
            logger.warning("[WEBHOOK] Invalid signature")
            return Response(status_code=401)

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

    logger.info(f"[WEBHOOK] Enqueuing event type={event_type} agent={agent_id} call={call_id}")

    # 4) Enqueue
    try:
        queue = get_queue()
        queue.enqueue(process_elevenlabs_event_job, payload)
    except Exception as e:
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
        total_calls, errors, calls_today, calls_last_7 = _merge_legacy_file_stats(
            agent_ids,
            db_agents,
            stats_by_day,
            stats_by_client,
            stats_by_category,
            stats_by_urgency,
            heatmap,
            today,
            last_7_start,
            total_calls,
            errors,
            calls_today,
            calls_last_7,
        )
    else:
        total_calls, errors, calls_today, calls_last_7 = _merge_legacy_file_stats(
            agent_ids,
            set(),
            stats_by_day,
            stats_by_client,
            stats_by_category,
            stats_by_urgency,
            heatmap,
            today,
            last_7_start,
            total_calls,
            errors,
            calls_today,
            calls_last_7,
        )

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


def _merge_legacy_file_stats(
    agent_ids: List[str],
    db_agents: set[str],
    stats_by_day: Dict[str, int],
    stats_by_client: Dict[str, int],
    stats_by_category: Dict[str, int],
    stats_by_urgency: Dict[str, int],
    heatmap: list[list[int]],
    today: date,
    last_7_start: date,
    total_calls: int,
    errors: int,
    calls_today: int,
    calls_last_7: int,
) -> tuple[int, int, int, int]:
    for agent_id in agent_ids:
        if agent_id in db_agents:
            continue
        log_path = LOGS_DIR / f"{agent_id}.log"
        if not log_path.exists():
            continue

        with log_path.open("r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue

                try:
                    entry = json.loads(line)
                except Exception:
                    continue

                ts = entry.get("timestamp")
                if not ts:
                    continue

                try:
                    dt = datetime.fromisoformat(ts)
                except Exception:
                    continue

                total_calls += 1

                day_str = dt.date().isoformat()
                stats_by_day[day_str] = stats_by_day.get(day_str, 0) + 1
                stats_by_client[agent_id] = stats_by_client.get(agent_id, 0) + 1

                d = dt.date()
                if d == today:
                    calls_today += 1
                if d >= last_7_start:
                    calls_last_7 += 1

                inner_data = entry.get("data", {})
                status = inner_data.get("status")

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

                ai = entry.get("ai_enrichment", {})
                cat = ai.get("category", "altro")
                urg = ai.get("urgency", "media")

                stats_by_category[cat] = stats_by_category.get(cat, 0) + 1
                stats_by_urgency[urg] = stats_by_urgency.get(urg, 0) + 1

                hour = dt.hour
                weekday = dt.weekday()
                if 0 <= hour < 24 and 0 <= weekday < 7:
                    heatmap[hour][weekday] += 1

    return total_calls, errors, calls_today, calls_last_7

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




class AdminUpdateUserRequest(BaseModel):
    studio_name: Optional[str] = None
    email: Optional[str] = None
    # Potentially other fields like notification_email if we add it later


def _apply_admin_user_update(user: User, payload: AdminUpdateUserRequest, db: Session) -> None:
    if payload.email is not None:
        if payload.email != user.email:
            existing = db.query(User).filter(User.email == payload.email).first()
            if existing:
                raise HTTPException(status_code=400, detail="Email already in use")
            user.email = payload.email

    if payload.studio_name is not None:
        user.studio_name = payload.studio_name

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

    if not sub:
        sub = db.query(Subscription).filter(
            Subscription.user_id == user.id
        ).order_by(Subscription.id.desc()).first()

    subscription_data = None
    if sub:
        subscription_data = {
            "state": sub.state,
            "plan_code": sub.plan.code if sub.plan else None,
            "cycle_start": sub.cycle_start.isoformat() if sub.cycle_start else None,
            "cycle_end": sub.cycle_end.isoformat() if sub.cycle_end else None,
            "updated_at": sub.updated_at.isoformat() if sub.updated_at else None,
        }

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

    # Client Logic
    minutes_limit = 0
    minutes_used = 0
    minutes_remaining = 0

    if sub and sub.plan:
        minutes_limit = sub.plan.minutes_per_cycle

        # Calculate usage for this subscription
        usage_seconds = db.query(func.sum(UsageEvent.billed_seconds)) \
                            .filter(UsageEvent.subscription_id == sub.id) \
                            .filter(UsageEvent.created_at >= sub.cycle_start) \
                            .filter(UsageEvent.created_at <= sub.cycle_end) \
                            .scalar() or 0

        minutes_used = usage_seconds / 60
        minutes_remaining = max(0, minutes_limit - minutes_used)

    return templates.TemplateResponse("client_dashboard.html", {
        "request": request,
        "user": user_dict,
        "subscription": subscription_data,
        "minutes_limit": minutes_limit,
        "minutes_used": minutes_used,
        "minutes_remaining": minutes_remaining
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

        if not sub:
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

    if not user.is_active:
        logger.warning(f"LOGIN_FAIL_INACTIVE: {normalized_username} id={user.id}")
        return RedirectResponse(url="/login?error=1", status_code=302)

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

    if logs:
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
    else:
        for agent_id in agent_ids:
            log_path = LOGS_DIR / f"{agent_id}.log"
            if not log_path.exists():
                continue

            with log_path.open("r", encoding="utf-8") as f:
                for line in f:
                    try:
                        raw = json.loads(line)
                        ts = raw.get("timestamp")
                        if not ts:
                            continue
                        d = datetime.fromisoformat(ts)
                        d_date = d.date()

                        if df and d_date < df:
                            continue
                        if dt and d_date > dt:
                            continue

                        analysis = raw.get("data", {}).get("analysis", {})
                        call_ok = analysis.get("call_successful")
                        is_failure = (call_ok == "failure")

                        if status == "success" and is_failure:
                            continue
                        if status == "failure" and not is_failure:
                            continue

                        item = {
                            "timestamp": ts,
                            "caller": raw.get("data", {}).get("user_id", "unknown"),
                            "status": "failure" if is_failure else "success",
                            "summary": raw.get("data", {}).get("analysis", {}).get("transcript_summary", "").strip(),
                            "duration_secs": raw.get("data", {}).get("metadata", {}).get("call_duration_secs", None),
                            "raw": raw
                        }

                        if q:
                            q_low = q.lower()
                            if q_low not in json.dumps(item, ensure_ascii=False).lower():
                                continue

                        items.append(item)
                    except Exception:
                        continue

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
