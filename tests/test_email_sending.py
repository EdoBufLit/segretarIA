from unittest.mock import MagicMock, patch

import mailer


def test_send_email_uses_starttls_and_headers(monkeypatch):
    monkeypatch.setattr(mailer, "EMAIL_FROM", "from@example.com")
    monkeypatch.setattr(mailer, "SMTP_HOST", "smtp.example.com")
    monkeypatch.setattr(mailer, "SMTP_PORT", 587)
    monkeypatch.setattr(mailer, "SMTP_USER", "smtp-user")
    monkeypatch.setattr(mailer, "SMTP_PASSWORD", "smtp-pass")

    smtp_instance = MagicMock()
    smtp_context = MagicMock()
    smtp_context.__enter__.return_value = smtp_instance
    smtp_context.__exit__.return_value = None

    with patch("mailer.smtplib.SMTP", return_value=smtp_context) as mock_smtp:
        mailer.send_email(
            to_addr="to@example.com",
            subject="Hello",
            body="Plain",
            html_body="<p>HTML</p>",
        )

    mock_smtp.assert_called_once_with("smtp.example.com", 587)
    smtp_instance.ehlo.assert_called()
    smtp_instance.starttls.assert_called_once()
    smtp_instance.login.assert_called_once_with("smtp-user", "smtp-pass")
    smtp_instance.send_message.assert_called_once()

    sent_message = smtp_instance.send_message.call_args[0][0]
    assert sent_message["From"] == "from@example.com"
    assert sent_message["To"] == "to@example.com"
    assert sent_message["Subject"] == "Hello"
