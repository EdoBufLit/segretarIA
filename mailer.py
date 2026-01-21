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

    # In a real app, this would send an email. For this environment, we'll just log it.
    print("--- SIMULATING EMAIL ---")
    print(f"To: {to_addr}")
    print(f"From: {EMAIL_FROM}")
    print(f"Subject: {subject}")
    print("Body:")
    print(html_body)
    print("--- END SIMULATING EMAIL ---")
