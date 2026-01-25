from mailer import send_email
import logging
from alerting import log_critical_error, track_email_success

logger = logging.getLogger("email_jobs")

def send_email_job(to_addr: str, subject: str, html_body: str):
    """
    Background job to send an email.
    """
    try:
        logger.info(f"Starting email job for {to_addr}")
        send_email(to_addr, subject, "Please view in HTML", html_body=html_body)
        track_email_success(to_addr)
        logger.info(f"Finished email job for {to_addr}")
    except Exception as e:
        logger.error(f"Email job failed: {e}")
        log_critical_error(f"Email job fallito verso {to_addr}: {e}", context={"recipient": to_addr, "subject": subject})
        raise # Let RQ handle retry/failure
