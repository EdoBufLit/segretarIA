import os
import json
from datetime import datetime
from typing import Any, Dict, Optional, List
from pydantic import BaseModel
from fastapi import FastAPI, HTTPException, Request, Body, Query
from fastapi.responses import HTMLResponse
from dotenv import load_dotenv
from mailer import send_email
from openai import OpenAI
import logging
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
from db import get_db
from models import User
from auth import verify_password, get_current_user, get_current_admin_user
from admin_service import AdminService
from client_service import ClientService
from billing_service import BillingService
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse, Response
import time

class RateLimitMiddleware(BaseHTTPMiddleware):
    def __init__(self, app):
        super().__init__(app)
        self.rate_limit_records = {}

    async def dispatch(self, request: Request, call_next):
        if request.url.path == "/login" or request.url.path.startswith("/admin/"):
            client_ip = request.client.host if request.client else "unknown"
            key = client_ip
            now = time.time()

            # Filter out timestamps older than 60 seconds
            self.rate_limit_records.setdefault(key, [])
            self.rate_limit_records[key] = [t for t in self.rate_limit_records[key] if now - t < 60]

            if len(self.rate_limit_records[key]) >= 5:
                return JSONResponse(status_code=429, content={"detail": "Too many requests"})

            self.rate_limit_records[key].append(now)

        return await call_next(request)

# ================== CONFIG BASE ==================

load_dotenv()
templates = Jinja2Templates(directory="templates")

app = FastAPI()
app.add_middleware(
    SessionMiddleware,
    secret_key=os.getenv("SESSION_SECRET", "super-secret-change-me"),
)
app.add_middleware(RateLimitMiddleware)

app.mount("/static", StaticFiles(directory="static"), name="static")
# Logger (va nei log di uvicorn)
logger = logging.getLogger("uvicorn.error")

# OpenAI
client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

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
LOGS_DIR = Path("logs")
LOGS_DIR.mkdir(exist_ok=True)
CLIENTS_FILE = os.getenv("CLIENTS_FILE", "clients.json")
CLIENTS: Dict[str, Dict[str, Any]] = {}
CLIENTS_MTIME: Optional[float] = None

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

def log_call(agent_id: str, data: Dict[str, Any]):
    """Salva una riga JSON in logs/<agent_id>.log"""
    log_path = LOGS_DIR / f"{agent_id}.log"
    entry = {
        "timestamp": datetime.utcnow().isoformat(),
        "agent_id": agent_id,
        "data": data
    }
    with log_path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    logger.info(f"[LOG] Salvata chiamata in {log_path}")


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


# ================== FUNZIONI DI SUPPORTO ==================

def summarize_call(transcript: str, existing_summary: Optional[str] = None) -> Dict[str, Any]:
    """
    Usa OpenAI per:
    - creare un riassunto leggibile della chiamata
    - estrarre metadati strutturati utili allo studio.
    """

    meta_text = ""
    if existing_summary:
        meta_text = f"\n\n[RIASSUNTO ORIGINALE ELEVENLABS]\n{existing_summary}"

    combined_text = transcript + meta_text

    instructions = f"""
Sei un assistente per la segreteria di uno studio professionale italiano.
Ti fornirò il transcript completo di una telefonata con un potenziale cliente.

Devi:
1. Creare un riassunto breve e chiaro (5-10 righe) per il professionista.
2. Estrarre alcuni dati strutturati.

IMPORTANTISSIMO:
- Rispondi SOLO con un oggetto JSON valido.
- Nessun testo prima o dopo il JSON.
- Nessun commento, nessuna spiegazione.

Struttura JSON richiesta:

{{
  "summary": "riassunto leggibile in italiano",
  "client_name": "nome e cognome se presente, altrimenti null",
  "client_phone": "numero di telefono se presente nel testo, altrimenti null",
  "client_email": "email se presente, altrimenti null",
  "matter_type": "civile/penale/lavoro/famiglia/condominio/recupero crediti/altro/ignoto",
  "main_reason": "motivo principale in 1-2 frasi",
  "urgency": "oggi/poche_giorni/non_urgente/ignoto",
  "deadlines": "eventuali scadenze/udienze citate, oppure null",
  "existing_client": "si/no/ignoto",
  "lawyer_name": "nome avvocato o professionista se citato, altrimenti null",
  "counterparty": "eventuale controparte (persona/azienda/ente) oppure null",
  "suggested_followup": "cosa dovrebbe fare lo studio come prossimo passo in 1-2 frasi"
}}

Transcript:
\"\"\"{combined_text}\"\"\"
"""

    resp = client.responses.create(
        model="gpt-4o-mini",
        input=instructions,
    )

    raw = resp.output_text

    # Proviamo a ripulire eventuale testo extra e prendere solo il JSON
    try:
        start = raw.index("{")
        end = raw.rindex("}") + 1
        json_str = raw[start:end]
    except ValueError:
        json_str = raw

    try:
        data = json.loads(json_str)
        if not isinstance(data, dict):
            raise TypeError("Output non è un oggetto JSON")
        return data
    except Exception as e:
        logger.warning(f"[OPENAI] JSON non valido, uso fallback: {e}")
        return {
            "summary": raw,
            "client_name": None,
            "client_phone": None,
            "client_email": None,
            "matter_type": "ignoto",
            "main_reason": None,
            "urgency": "ignoto",
            "deadlines": None,
            "existing_client": "ignoto",
            "lawyer_name": None,
            "counterparty": None,
            "suggested_followup": None,
        }


def build_email_body_html(
    transcript_text: str,
    analysis: Dict[str, Any],
    caller_number: str,
    started_at: Optional[str],
    ended_at: Optional[str],
    raw_payload: Dict[str, Any],  # non usato, solo compatibilità
    studio_name: str,
    agency_name: str,
) -> str:
    """
    Costruisce una mail HTML elegante per il singolo studio.
    Nessun transcript, nessun raw payload.
    Solo dati utili, puliti.
    """

    started = started_at or "N/D"
    ended = ended_at or "N/D"

    urgenza = analysis.get("urgency", "ignoto")

    if urgenza == "oggi":
        urgenza_label = "URGENTE (entro oggi)"
        urgenza_color = "#ff3b30"
    elif urgenza == "poche_giorni":
        urgenza_label = "Importante (entro pochi giorni)"
        urgenza_color = "#ff9500"
    elif urgenza == "non_urgente":
        urgenza_label = "Non urgente"
        urgenza_color = "#34c759"
    else:
        urgenza_label = "Urgenza non chiara"
        urgenza_color = "#8e8e93"

    html = f"""
<html>
  <body style="font-family: Arial, sans-serif; background-color: #f7f7f7; padding: 20px;">
    
    <div style="max-width: 650px; margin: auto; background: white; padding: 25px; border-radius: 12px; box-shadow: 0 2px 10px rgba(0,0,0,0.05);">

      <h2 style="color: #333;">Segreteria IA – Nuova chiamata per <span style="color:#0066cc;">{studio_name}</span></h2>
      <p style="color:#777; font-size:13px; margin-top:4px;">Servizio gestito da {agency_name}</p>

      <hr style="border: none; border-top: 1px solid #eee; margin: 20px 0;">

      <h3 style="color: #333; margin-bottom: 10px;">📞 Dati della chiamata</h3>
      <p><strong>Numero chiamante:</strong> {caller_number}</p>
      <p><strong>Inizio:</strong> {started}</p>
      <p><strong>Fine:</strong> {ended}</p>

      <div style="margin: 20px 0; padding: 12px 15px; background: {urgenza_color}; color: white; border-radius: 8px; font-size: 15px;">
        <strong>URGENZA:</strong> {urgenza_label}
      </div>

      <h3 style="color: #333; margin-bottom: 10px;">👤 Dati cliente (estratti automaticamente)</h3>
      <p><strong>Nome:</strong> {analysis.get('client_name')}</p>
      <p><strong>Telefono dichiarato:</strong> {analysis.get('client_phone')}</p>
      <p><strong>Email dichiarata:</strong> {analysis.get('client_email')}</p>
      <p><strong>Cliente già esistente:</strong> {analysis.get('existing_client')}</p>
      <p><strong>Professionista citato:</strong> {analysis.get('lawyer_name')}</p>

      <h3 style="color: #333; margin-top: 25px;">📂 Oggetto della questione</h3>
      <p><strong>Tipo di questione:</strong> {analysis.get('matter_type')}</p>
      <p><strong>Motivo principale:</strong> {analysis.get('main_reason')}</p>
      <p><strong>Controparte:</strong> {analysis.get('counterparty')}</p>
      <p><strong>Scadenze/udienze:</strong> {analysis.get('deadlines')}</p>

      <h3 style="color: #333; margin-top: 25px;">📝 Riassunto della chiamata</h3>
      <p style="white-space: pre-line; line-height: 1.5;">{analysis.get('summary')}</p>

      <h3 style="color: #333; margin-top: 25px;">👉 Prossimi passi consigliati</h3>
      <p>{analysis.get('suggested_followup')}</p>

      <hr style="border: none; border-top: 1px solid #eee; margin: 30px 0 15px;">
      <p style="color:#999; font-size:12px; text-align:center;">Email generata automaticamente dalla Segreteria IA.</p>

    </div>
  </body>
</html>
    """

    return html


# ================== ENDPOINT DI TEST ==================

@app.get("/")
async def root():
    return {"status": "ok", "message": "Segreteria IA ElevenLabs backend attivo."}


# ================== ADMIN ENDPOINTS ==================

@app.get("/admin/clients", response_class=HTMLResponse)
async def admin_get_clients(request: Request, db: Session = Depends(get_db), admin: User = Depends(get_current_admin_user)):
    service = AdminService(db, admin.username)
    clients = service.get_clients()
    return templates.TemplateResponse("admin_clients.html", {"request": request, "clients": clients})

@app.post("/admin/clients/create")
async def admin_create_client(username: str = Form(...), email: str = Form(...), password: str = Form(...), studio_name: str = Form(...), db: Session = Depends(get_db), admin: User = Depends(get_current_admin_user)):
    service = AdminService(db, admin.username)
    try:
        client = service.create_client(username, email, password, studio_name)
        service.sync_clients_to_json()
        return {"status": "ok", "client_id": client.id}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

@app.post("/admin/agents/create")
async def admin_create_agent(agent_id: str = Form(...), display_name: str = Form(...), phone_number_id: str = Form(None), db: Session = Depends(get_db), admin: User = Depends(get_current_admin_user)):
    service = AdminService(db, admin.username)
    try:
        agent = service.create_agent(agent_id, display_name, phone_number_id)
        service.sync_clients_to_json()
        return {"status": "ok", "agent_id": agent.id}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

@app.post("/admin/clients/{user_id}/assign-agent")
async def admin_assign_agent(user_id: int, agent_id: int = Form(...), db: Session = Depends(get_db), admin: User = Depends(get_current_admin_user)):
    service = AdminService(db, admin.username)
    try:
        client = service.assign_agent_to_client(user_id, agent_id)
        service.sync_clients_to_json()
        return {"status": "ok", "client_id": client.id, "assigned_agents": [a.id for a in client.agents]}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

@app.post("/admin/clients/{user_id}/create-subscription")
async def admin_create_subscription(user_id: int, plan_code: str = Form(...), db: Session = Depends(get_db), admin: User = Depends(get_current_admin_user)):
    service = AdminService(db, admin.username)
    try:
        subscription = service.create_or_update_subscription(user_id, plan_code)
        return {"status": "ok", "subscription_id": subscription.id, "state": subscription.state}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

@app.post("/admin/users/{user_id}/reset-password")
async def admin_reset_user_password(user_id: int, db: Session = Depends(get_db), admin: User = Depends(get_current_admin_user)):
    service = AdminService(db, admin.username)
    try:
        service.reset_password_random(user_id)
        return {"status": "ok"}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

@app.post("/admin/sync-clients-json")
async def admin_sync_clients_json(db: Session = Depends(get_db), admin: User = Depends(get_current_admin_user)):
    service = AdminService(db, admin.username)
    summary = service.sync_clients_to_json()
    return {"status": "ok", **summary}

@app.get("/admin/export/minutes")
async def admin_export_minutes(
    from_date: str = Query(..., alias="from"),
    to_date: str = Query(..., alias="to"),
    db: Session = Depends(get_db),
    admin: User = Depends(get_current_admin_user)
):
    service = AdminService(db, admin.username)
    try:
        dt_from = datetime.fromisoformat(from_date)
        dt_to = datetime.fromisoformat(to_date)

        # Ensure 'to_date' covers the whole day if it's just a date
        if "T" not in to_date and len(to_date) == 10:
             dt_to = dt_to + timedelta(hours=23, minutes=59, seconds=59)

        csv_content = service.export_minutes_csv(dt_from, dt_to)

        filename = f"minutes_{from_date}_{to_date}.csv"
        return Response(
            content=csv_content,
            media_type="text/csv",
            headers={"Content-Disposition": f"attachment; filename={filename}"}
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail="Invalid date format. Use ISO format (YYYY-MM-DD or YYYY-MM-DDTHH:MM:SS)")
    except Exception as e:
         raise HTTPException(status_code=500, detail=str(e))

@app.get("/admin/phone-numbers", response_class=HTMLResponse)
async def admin_get_phone_numbers(request: Request, db: Session = Depends(get_db), admin: User = Depends(get_current_admin_user)):
    service = AdminService(db, admin.username)
    numbers = service.get_all_phone_numbers()
    return templates.TemplateResponse("admin_phonenumbers.html", {"request": request, "numbers": numbers})

@app.post("/admin/phone-numbers/create") # Temporary for testing
async def admin_create_phone_number(e164: str = Form(...), user_id: int = Form(...), db: Session = Depends(get_db), admin: User = Depends(get_current_admin_user)):
    service = AdminService(db, admin.username)
    try:
        phone = service.create_phone_number(e164, user_id)
        return {"status": "ok", "phone_number_id": phone.id}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

@app.post("/admin/phone-numbers/{phone_id}/mark-released")
async def admin_mark_phone_number_released(phone_id: int, db: Session = Depends(get_db), admin: User = Depends(get_current_admin_user)):
    service = AdminService(db, admin.username)
    try:
        service.mark_phone_number_released(phone_id)
        return RedirectResponse(url="/admin/phone-numbers", status_code=303)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))

@app.post("/admin/phone-numbers/{phone_id}/cancel-deprovision")
async def admin_cancel_deprovision(phone_id: int, db: Session = Depends(get_db), admin: User = Depends(get_current_admin_user)):
    service = AdminService(db, admin.username)
    try:
        service.cancel_phone_number_deprovisioning(phone_id)
        return RedirectResponse(url="/admin/phone-numbers", status_code=303)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


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


# ================== WEBHOOK ELEVENLABS ==================

def extract_transcript_text(payload: dict) -> str:
    """
    Unisce i messaggi 'agent' e 'user' in un testo unico, leggibile.
    """
    turns = payload.get("data", {}).get("transcript", [])
    lines = []
    for t in turns:
        role = t.get("role")
        msg = t.get("message", "")
        if not msg:
            continue
        prefix = "Cliente: " if role == "user" else "Assistente: "
        lines.append(prefix + msg)
    return "\n".join(lines)

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
    client_cfg = get_client_config(agent_id)
    studio_name = client_cfg["studio_name"]
    email_to = client_cfg["email_to"]

    # 4) Transcript
    transcript_turns = data.get("transcript", []) or []
    transcript_lines: List[str] = []
    for turn in transcript_turns:
        role = str(turn.get("role", "unknown")).upper()
        msg = turn.get("message", "")
        transcript_lines.append(f"{role}: {msg}")
    transcript_text = "\n".join(transcript_lines) if transcript_lines else "(Transcript vuoto)"

    # 5) Metadati chiamata
    metadata: Dict[str, Any] = data.get("metadata", {}) or {}

    caller_number = (
        metadata.get("phone_call", {}).get("external_number")
        or metadata.get("from_number")
        or metadata.get("caller_number")
        or metadata.get("phone_number")
        or "N/D"
    )

    started_at: Optional[str] = None
    ended_at: Optional[str] = None
    start_unix = metadata.get("start_time_unix_secs")
    duration_secs = metadata.get("call_duration_secs")

    try:
        if isinstance(start_unix, (int, float)):
            started_dt = datetime.utcfromtimestamp(start_unix)
            started_at = started_dt.isoformat()
            if isinstance(duration_secs, (int, float)):
                ended_dt = datetime.utcfromtimestamp(start_unix + duration_secs)
                ended_at = ended_dt.isoformat()
    except Exception as e:
        logger.warning(f"[WEBHOOK] Errore calcolo orari chiamata: {e}")

    # 6) Riassunto già fornito da ElevenLabs (se presente)
    analysis_obj: Dict[str, Any] = data.get("analysis", {}) or {}
    el_summary: Optional[str] = analysis_obj.get("transcript_summary")

    # 7) OpenAI per analisi strutturata
    try:
        analysis_structured = summarize_call(transcript_text, el_summary)
    except Exception as e:
        logger.exception("[OPENAI] Errore in summarize_call")
        analysis_structured = {
            "summary": transcript_text,
            "client_name": None,
            "client_phone": None,
            "client_email": None,
            "matter_type": "ignoto",
            "main_reason": None,
            "urgency": "ignoto",
            "deadlines": None,
            "existing_client": "ignoto",
            "lawyer_name": None,
            "counterparty": None,
            "suggested_followup": None,
        }

    # Determinazione status
    status = "success"
    if duration_secs and duration_secs < 3:
        status = "failure"

    log_call(agent_id, {
        "transcript_text": transcript_text,
        "analysis": analysis_structured,
        "caller_number": caller_number,
        "started_at": started_at,
        "ended_at": ended_at,
        "duration_secs": duration_secs,
        "status": status,
        "summary": analysis_structured.get("summary")
    })
    # 8) Mail
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

        send_email(email_to, subject, email_body)
    except Exception as e:
        logger.exception("[EMAIL] Errore invio email/build")
        return {"status": "error", "reason": f"email error: {e}"}

    logger.info(f"[WEBHOOK] Chiamata gestita correttamente per {studio_name} ({agent_id})")

    # Meter the call
    if duration_secs and agent_id:
        call_id = metadata.get("phone_call", {}).get("call_sid") or data.get("conversation_id")
        if call_id:
            with SessionLocal() as db:
                billing_service = BillingService(db)
                billing_service.meter_call(
                    agent_id=agent_id,
                    duration_secs=int(duration_secs),
                    call_id=call_id,
                    started_at=datetime.fromisoformat(started_at) if started_at else datetime.utcnow() - timedelta(seconds=duration_secs),
                    ended_at=datetime.fromisoformat(ended_at) if ended_at else datetime.utcnow()
                )
        else:
            logger.warning("[METERING] No unique call_id found in webhook payload.")

    return {"status": "ok", "message": "Webhook ricevuto e email inviata."}

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
async def read_users_me(current_user: User = Depends(get_current_user)):
    return {
        "username": current_user.username,
        "role": current_user.role,
        "studio_name": current_user.studio_name,
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

    client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

def enrich_call_with_ai(transcript: str) -> dict:
    """
    Usa OpenAI per estrarre info strutturate dalla chiamata.
    Ritorna sempre un dict Python, anche se il modello sbarella.
    """
    system_msg = (
        "Sei un assistente che analizza le trascrizioni delle chiamate "
        "a uno studio legale.\n"
        "Devi restituire SOLO un JSON valido con queste chiavi:\n"
        "category: string (es. 'lavoro', 'civile', 'penale', 'famiglia', 'amministrativo', 'altro')\n"
        "urgency: string ('bassa','media','alta','estrema')\n"
        "callback_needed: boolean\n"
        "short_title: string (max 80 caratteri, titolo riassuntivo)\n"
        "tags: lista di 2-5 parole chiave\n"
        "description: breve descrizione (1-2 frasi sintetiche in italiano)\n"
    )

    user_msg = (
        "Trascrizione completa della chiamata (in italiano):\n\n"
        f"{transcript}"
    )

    try:
        resp = client.chat.completions.create(
            model="gpt-4.1-mini",
            response_format={"type": "json_object"},
            messages=[
                {"role": "system", "content": system_msg},
                {"role": "user", "content": user_msg},
            ],
            temperature=0.2,
        )
        content = resp.choices[0].message.content
        data = json.loads(content)
        return data
    except Exception as e:
        print("AI enrichment error:", e)
        return {
            "category": "altro",
            "urgency": "media",
            "callback_needed": True,
            "short_title": "Richiesta non classificata",
            "tags": [],
            "description": "Impossibile classificare la chiamata (errore interno).",
        }




    # …qui il tuo log_call(entry, agent_id) o simile…
    # …e la parte di email che già hai…
@app.post("/clients/{agent_id}/test-call")
async def test_call(agent_id: str):
    """
    Avvia una chiamata di test tramite ElevenLabs/Twilio verso il numero di test
    configurato per questo cliente.
    """
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