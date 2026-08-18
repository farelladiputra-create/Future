"""Email delivery over SMTP, carrying the full HTML brief.

Named `email_report` rather than `email` so it cannot shadow the standard
library package it imports from.
"""

from __future__ import annotations

import logging
import os
import smtplib
import ssl
from email.message import EmailMessage

log = logging.getLogger(__name__)

TIMEOUT = 30.0


def send(subject: str, text_body: str, html_body: str) -> bool:
    """Send the brief. Returns False and logs rather than raising."""
    host = os.environ.get("SMTP_HOST")
    user = os.environ.get("SMTP_USER")
    password = os.environ.get("SMTP_PASSWORD")
    recipient = os.environ.get("REPORT_EMAIL_TO")
    if not all((host, user, password, recipient)):
        log.info("email not configured, skipping")
        return False

    port = int(os.environ.get("SMTP_PORT", "465"))
    sender = os.environ.get("REPORT_EMAIL_FROM", user)

    message = EmailMessage()
    message["Subject"] = subject
    message["From"] = sender
    message["To"] = recipient
    message.set_content(text_body)
    message.add_alternative(html_body, subtype="html")

    try:
        context = ssl.create_default_context()
        if port == 587:
            with smtplib.SMTP(host, port, timeout=TIMEOUT) as server:
                server.starttls(context=context)
                server.login(user, password)
                server.send_message(message)
        else:
            with smtplib.SMTP_SSL(host, port, timeout=TIMEOUT, context=context) as server:
                server.login(user, password)
                server.send_message(message)
    except (smtplib.SMTPException, OSError) as exc:
        log.warning("email send failed: %s", exc)
        return False
    return True
