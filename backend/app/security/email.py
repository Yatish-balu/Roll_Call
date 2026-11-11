"""Email delivery abstraction for security notifications.

The application must never expose a secret (password reset token, MFA
recovery code) through an API response, and it must never claim that a
message was delivered when no provider is configured.

Providers implement :class:`EmailProvider`. The factory returns:

* the configured provider when one is available,
* otherwise a :class:`NullEmailProvider` that reports ``delivered=False``
  and ``configured=False`` so the caller can answer generically and record
  the missing delivery configuration as a deployment blocker.
"""

from __future__ import annotations

import logging
import os
import smtplib
from dataclasses import dataclass, field
from email.message import EmailMessage
from typing import Any, Dict, Optional

logger = logging.getLogger("rollcall.security.email")


@dataclass
class EmailResult:
    """Outcome of a delivery attempt."""

    delivered: bool
    configured: bool
    detail: str = ""


class EmailProvider:
    """Interface for delivering a security notification."""

    name = "base"

    def send(self, to_address: str, subject: str, body: str) -> EmailResult:
        raise NotImplementedError


@dataclass
class NullEmailProvider(EmailProvider):
    """Provider used when no delivery channel is configured."""

    name: str = "null"
    reason: str = "No email provider is configured."

    def send(self, to_address: str, subject: str, body: str) -> EmailResult:
        logger.error(
            "Password reset notification could not be delivered: %s "
            "(SECURITY: configure an email provider before relying on password reset).",
            self.reason,
        )
        return EmailResult(delivered=False, configured=False, detail=self.reason)


@dataclass
class SmtpEmailProvider(EmailProvider):
    """Minimal SMTP provider (no credentials are read from the database)."""

    host: str
    port: int = 587
    username: Optional[str] = None
    password: Optional[str] = None
    sender: str = "no-reply@rollcall.internal"
    use_tls: bool = True
    name: str = "smtp"

    def send(self, to_address: str, subject: str, body: str) -> EmailResult:
        message = EmailMessage()
        message["From"] = self.sender
        message["To"] = to_address
        message["Subject"] = subject
        message.set_content(body)
        try:
            with smtplib.SMTP(self.host, self.port, timeout=15) as server:
                if self.use_tls:
                    server.starttls()
                if self.username and self.password:
                    server.login(self.username, self.password)
                server.send_message(message)
            return EmailResult(delivered=True, configured=True)
        except Exception as exc:
            logger.error("Email delivery failed: %s", exc)
            return EmailResult(delivered=False, configured=True, detail=str(exc))


def get_email_provider() -> EmailProvider:
    """Return the configured provider, or the null provider when none is set.

    Configuration comes from the environment only (``SMTP_HOST`` etc.). No
    credential is stored in the database and nothing is invented here.
    """
    host = os.getenv("SMTP_HOST", "").strip()
    if not host:
        return NullEmailProvider()
    try:
        port = int(os.getenv("SMTP_PORT", "587"))
    except ValueError:
        port = 587
    return SmtpEmailProvider(
        host=host,
        port=port,
        username=os.getenv("SMTP_USERNAME") or None,
        password=os.getenv("SMTP_PASSWORD") or None,
        sender=os.getenv("SMTP_SENDER", "no-reply@rollcall.internal"),
        use_tls=os.getenv("SMTP_STARTTLS", "1") not in ("0", "false", "False"),
    )
