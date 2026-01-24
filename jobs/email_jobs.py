from mailer import send_email
import logging

logger = logging.getLogger("email_jobs")

def send_email_job(to_addr: str, subject: str, html_body: str):
    """
    Background job to send an email.
    """
    try:
        logger.info(f"Starting email job for {to_addr}")
        send_email(to_addr, subject, "Please view in HTML", html_body=html_body)
        logger.info(f"Finished email job for {to_addr}")
    except Exception as e:
        logger.error(f"Email job failed: {e}")
        raise # Let RQ handle retry/failure
