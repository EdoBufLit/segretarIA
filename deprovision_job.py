from datetime import datetime, timedelta
from db import SessionLocal
from models import PhoneNumber
from mailer import send_email
import os
import logging

logger = logging.getLogger("deprovision_job")

def run_deprovision_job():
    db = SessionLocal()
    print("Running deprovisioning job...")

    try:
        now = datetime.utcnow()

        numbers_to_deprovision = db.query(PhoneNumber).filter(
            PhoneNumber.provider == "ehiweb",
            PhoneNumber.status == "pending_deprovision",
            PhoneNumber.deprovision_at <= now,
            PhoneNumber.notified_at == None
        ).all()

        if not numbers_to_deprovision:
            print("No phone numbers due for deprovisioning.")
            return

        admin_email = os.getenv("ADMIN_EMAIL", "admin@example.com")

        for number in numbers_to_deprovision:
            print(f"Sending deprovisioning notification for {number.e164}...")

            subject = f"[ACTION REQUIRED] Disdire numero Ehiweb {number.e164} (costo {number.monthly_cost_cents / 100}€/mese)"
            body = f"""
            <p><strong>Azione manuale richiesta:</strong></p>
            <p>Il numero di telefono <b>{number.e164}</b> è dovuto per la disdetta manuale dal pannello Ehiweb.</p>
            <ul>
                <li>Cliente: {number.user.studio_name or number.user.username} (ID: {number.user.id})</li>
                <li>Numero: {number.e164}</li>
                <li>Costo mensile: {number.monthly_cost_cents / 100}€</li>
                <li>Data di disdetta programmata: {number.deprovision_at.strftime('%Y-%m-%d')}</li>
            </ul>
            <p><strong>Checklist:</strong></p>
            <ol>
                <li>Apri il pannello di controllo Ehiweb.</li>
                <li>Seleziona il numero di telefono <b>{number.e164}</b>.</li>
                <li>Disattiva il numero.</li>
                <li>Una volta completato, torna alla dashboard di amministrazione e segna il numero come 'Rilasciato'.</li>
            </ol>
            """

            try:
                send_email(admin_email, subject, body)
                number.notified_at = now
                db.commit()
            except Exception as e:
                logger.error("Failed to send deprovision email for %s: %s", number.e164, e)
                db.rollback()

        print(f"Sent {len(numbers_to_deprovision)} deprovisioning notifications.")

    except Exception as e:
        print(f"An error occurred during the deprovisioning job: {e}")
        db.rollback()
    finally:
        db.close()

if __name__ == "__main__":
    run_deprovision_job()
