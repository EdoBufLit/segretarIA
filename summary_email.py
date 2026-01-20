import os
import json
import smtplib
from email.message import EmailMessage
from typing import Dict, Any, Optional

from pathlib import Path
from dotenv import load_dotenv
from openai import OpenAI

# Carica .env in modo esplicito dalla cartella del progetto
ENV_PATH = Path(__file__).resolve().parent / ".env"
load_dotenv(ENV_PATH, override=True)


def _get_openai_client() -> OpenAI:
    """
    Crea un client OpenAI leggendo la chiave da OPENAI_API_KEY.
    Se non c'è, solleva un errore chiaro.
    """
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        raise RuntimeError(
            "OPENAI_API_KEY non trovata. "
            "Controlla il file .env nella stessa cartella di main.py "
            "e assicurati che la variabile sia impostata."
        )
    return OpenAI(api_key=api_key)


SMTP_HOST = os.getenv("SMTP_HOST")
SMTP_PORT = int(os.getenv("SMTP_PORT", "465"))
SMTP_USERNAME = os.getenv("SMTP_USERNAME")
SMTP_PASSWORD = os.getenv("SMTP_PASSWORD")
EMAIL_FROM = os.getenv("EMAIL_FROM", SMTP_USERNAME or "")
EMAIL_TO = os.getenv("EMAIL_TO", "")


def summarize_transcript(transcript_text: str) -> Dict[str, Any]:
    """
    Usa GPT per riassumere la chiamata ed estrarre i dati chiave.
    Restituisce un dict con summary + campi strutturati.
    """
    if not transcript_text.strip():
        return {
            "summary": "Nessun contenuto (trascrizione vuota).",
            "name": None,
            "reason": None,
            "request_type": None,
            "urgency": "media",
            "callback_contact": None,
        }

    system_prompt = (
        "Sei la segreteria telefonica intelligente di uno studio legale.\n"
        "Ricevi la trascrizione (assistente + cliente) di una chiamata.\n"
        "Devi concentrarti su ciò che chiede il CLIENTE.\n"
        "Obiettivo:\n"
        "- creare un riassunto chiaro e conciso (max 3-4 frasi) in italiano;\n"
        "- estrarre, se possibile: nome del chiamante, motivo della chiamata,\n"
        "  tipo di richiesta (es. appuntamento, consulenza, urgenza, pagamento, pratica in corso),\n"
        "  livello di urgenza (bassa, media, alta), eventuale recapito (telefono o email citati).\n"
        "Rispondi SOLO in JSON con le chiavi:\n"
        "{\n"
        '  \"summary\": string,\n'
        '  \"name\": string | null,\n'
        '  \"reason\": string | null,\n'
        '  \"request_type\": string | null,\n'
        '  \"urgency\": \"bassa\" | \"media\" | \"alta\",\n'
        '  \"callback_contact\": string | null\n'
        "}\n"
    )

    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": transcript_text},
    ]

    client = _get_openai_client()

    resp = client.responses.create(
        model="gpt-4.1-mini",
        input=messages,
        response_format={"type": "json_object"},
    )

    raw = resp.output_text
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        parsed = {
            "summary": raw,
            "name": None,
            "reason": None,
            "request_type": None,
            "urgency": "media",
            "callback_contact": None,
        }

    return parsed


def send_summary_email(
    transcript_text: str,
    call_sid: Optional[str] = None,
    from_number: Optional[str] = None,
    to_number: Optional[str] = None,
):
    """
    Manda l'email allo studio con:
      - riassunto
      - dati estratti
      - trascrizione completa
      - info base sulla chiamata
    """
    if not (SMTP_HOST and SMTP_PORT and SMTP_USERNAME and SMTP_PASSWORD and EMAIL_TO):
        print("[WARN] Config SMTP/EMAIL mancante, niente mail inviata.")
        return

    data = summarize_transcript(transcript_text)

    summary = data.get("summary", "")
    name = data.get("name")
    reason = data.get("reason")
    request_type = data.get("request_type")
    urgency = data.get("urgency")
    callback_contact = data.get("callback_contact")

    subject = "[Segreteria IA] Nuovo messaggio per Studio Legale"

    body_lines = [
        "Nuova chiamata gestita dall'assistente vocale IA.\n",
        f"Call SID: {call_sid or 'n/d'}",
        f"Da: {from_number or 'n/d'}",
        f"A: {to_number or 'n/d'}",
        "",
        "=== RIASSUNTO (IA) ===",
        summary or "Nessun riassunto disponibile.",
        "",
        "=== DATI ESTRATTI ===",
        f"Nome: {name}",
        f"Motivo: {reason}",
        f"Tipo richiesta: {request_type}",
        f"Urgenza: {urgency}",
        f"Recapito indicato: {callback_contact}",
        "",
        "=== TRASCRIZIONE COMPLETA ===",
        transcript_text or "Nessun testo disponibile.",
        "",
        "Email generata automaticamente dalla Segreteria Telefonica IA.",
    ]
    body = "\n".join(body_lines)

    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = EMAIL_FROM
    msg["To"] = EMAIL_TO
    msg.set_content(body)

    with smtplib.SMTP_SSL(SMTP_HOST, SMTP_PORT) as server:
        server.login(SMTP_USERNAME, SMTP_PASSWORD)
        server.send_message(msg)

    print("[INFO] Email di riassunto inviata.")

