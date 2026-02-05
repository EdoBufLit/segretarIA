import os
import smtplib
from email.message import EmailMessage
from dotenv import load_dotenv

load_dotenv()

EMAIL_FROM = os.getenv("EMAIL_FROM")
SMTP_HOST = os.getenv("SMTP_HOST", "smtp.gmail.com")
SMTP_PORT = int(os.getenv("SMTP_PORT", "587"))
SMTP_USER = os.getenv("SMTP_USER")
SMTP_PASSWORD = os.getenv("SMTP_PASSWORD")

def send_email(to_addr: str, subject: str, html_body: str):
    """
    Sends an email in HTML format with a plain text fallback.
    """
    if not all([EMAIL_FROM, SMTP_HOST, SMTP_USER, SMTP_PASSWORD]):
        raise RuntimeError("SMTP configuration is incomplete. Check your .env file.")

    if not to_addr:
        raise ValueError("Email recipient (to_addr) is missing.")

    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = EMAIL_FROM
    msg["To"] = to_addr

    # Plain text fallback
    msg.set_content("This email requires an HTML-compatible client.")

    # HTML content
    msg.add_alternative(html_body, subtype="html")

    # Mock mode for QA/Testing
    if SMTP_HOST == "mock":
        print(f"Email sent to {to_addr} with subject: '{subject}' (MOCK)")
        return

    try:
        with smtplib.SMTP(SMTP_HOST, SMTP_PORT) as server:
            server.starttls()
            server.login(SMTP_USER, SMTP_PASSWORD)
            server.send_message(msg)
        print(f"Email sent to {to_addr} with subject: '{subject}'")
    except Exception as e:
        print(f"Failed to send email to {to_addr}: {e}")
        # In a real app, you'd want more robust error handling/logging here
        raise
