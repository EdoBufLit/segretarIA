import os
import json
from typing import Any, Dict, Optional, List
from openai import OpenAI
import logging
from pathlib import Path
from datetime import datetime

logger = logging.getLogger("call_utils")
client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

LOGS_DIR = Path("logs")
LOGS_DIR.mkdir(exist_ok=True)

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

    resp = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[{"role": "user", "content": instructions}],
    )

    raw = resp.choices[0].message.content

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
            model="gpt-4o-mini",
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
        logger.warning(f"AI enrichment error: {e}")
        return {
            "category": "altro",
            "urgency": "media",
            "callback_needed": True,
            "short_title": "Richiesta non classificata",
            "tags": [],
            "description": "Impossibile classificare la chiamata (errore interno).",
        }
