"""stock.emailer -- small SMTP helper for operator reports and failure alerts."""
from __future__ import annotations

import logging
import smtplib
from dataclasses import dataclass
from email.message import EmailMessage

from stock.config import get_settings

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class EmailSendResult:
    """Result of a best-effort email send."""

    sent: bool
    detail: str


def send_email(
    *,
    subject: str,
    body: str,
    to_addr: str | None = None,
) -> EmailSendResult:
    """Send a plain-text email through configured SMTP settings.

    Missing SMTP settings are treated as a logged no-op so scheduled jobs do not
    fail just because email delivery has not been configured yet.
    """
    settings = get_settings()
    recipient = (to_addr or settings.daily_report_email_to).strip()
    if not recipient:
        return EmailSendResult(sent=False, detail="email recipient is empty")
    if not settings.smtp_host or not settings.smtp_username or not settings.smtp_password:
        detail = "SMTP not configured; set SMTP_HOST, SMTP_USERNAME, SMTP_PASSWORD"
        logger.warning("email skipped for %s: %s", recipient, detail)
        return EmailSendResult(sent=False, detail=detail)

    sender = (settings.smtp_from or settings.smtp_username).strip()
    msg = EmailMessage()
    msg["From"] = sender
    msg["To"] = recipient
    msg["Subject"] = subject
    msg.set_content(body)

    try:
        with smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=30) as smtp:
            if settings.smtp_starttls:
                smtp.starttls()
            smtp.login(settings.smtp_username, settings.smtp_password)
            smtp.send_message(msg)
    except Exception as exc:
        logger.exception("email send failed to %s", recipient)
        return EmailSendResult(sent=False, detail=str(exc))

    return EmailSendResult(sent=True, detail="sent")
