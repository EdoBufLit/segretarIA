import os
import smtplib
import logging
from email.message import EmailMessage
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger("mailer")

EMAIL_FROM = os.getenv("EMAIL_FROM")
SMTP_HOST = os.getenv("SMTP_HOST", "smtp.gmail.com")
SMTP_PORT = int(os.getenv("SMTP_PORT", "587"))
SMTP_USER = os.getenv("SMTP_USER")
SMTP_PASSWORD = os.getenv("SMTP_PASSWORD")

def send_email(to_addr: str, subject: str, body: str, html_body: str = None, reply_to: str = None):
    """
    Sends an email.
    Args:
        to_addr: Recipient email
        subject: Subject line
        body: Plain text body (or HTML if html_body is None, for legacy compatibility)
        html_body: Optional HTML version. If provided, body is used as fallback.
                   If not provided, body is assumed to be HTML and used for both (with stripped fallback if possible, or just same).
        reply_to: Optional email address for the Reply-To header.
    """
    if not all([EMAIL_FROM, SMTP_HOST, SMTP_USER, SMTP_PASSWORD]):
        raise RuntimeError("SMTP configuration is incomplete. Check your .env file.")

    if not to_addr:
        raise ValueError("Email recipient (to_addr) is missing.")

    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = EMAIL_FROM
    msg["To"] = to_addr
    if reply_to:
        msg["Reply-To"] = reply_to

    # Determine plain text and HTML content
    if html_body:
        text_content = body
        html_content = html_body
    else:
        # Legacy behavior: body argument is likely HTML
        # In a real scenario, we should strip tags for text_content, but for now:
        text_content = "This email requires an HTML-compatible client."
        html_content = body

    msg.set_content(text_content)
    msg.add_alternative(html_content, subtype="html")

    # Mock mode for QA/Testing
    if SMTP_HOST == "mock":
        print(f"Email sent to {to_addr} with subject: '{subject}' (MOCK)")
        return

    try:
        with smtplib.SMTP(SMTP_HOST, SMTP_PORT) as server:
            server.ehlo()
            server.starttls()
            server.ehlo()
            server.login(SMTP_USER, SMTP_PASSWORD)
            server.send_message(msg)
        logger.info("Email sent to %s with subject: %s", to_addr, subject)
    except (smtplib.SMTPException, TimeoutError, OSError) as e:
        logger.error("Failed to send email to %s: %s", to_addr, e)
        raise
    except Exception as e:
        logger.error("Unexpected error sending email to %s: %s", to_addr, e)
        raise
