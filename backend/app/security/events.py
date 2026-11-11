"""Structured security event logging.

Security events are *operational* records: they describe what the system
noticed (a failed login, an access denial, a rate-limit hit, a suspicious
pattern, a failed audit-chain verification). They are deliberately kept
separate from the application audit log in ``audit_log``: the audit log is the
business record of what a user did, the security event log is the operational
signal that something might be wrong.

Guarantees:

* Events are emitted as single-line JSON so they can be shipped to a SIEM.
* Secrets are never written: password, token, JWT, refresh token, MFA secret,
  cookie and credential-like values are redacted before serialization.
* The logger is a dedicated logger (``rollcall.security``) so the stream can be
  routed independently from the application logs.
"""

from __future__ import annotations

import json
import logging
import os
import threading
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, Iterable, Mapping, Optional

from app.security.context import get_request_id

SECURITY_LOGGER_NAME = "rollcall.security"

#: Values whose key matches one of these markers are never logged.
SENSITIVE_KEYS = frozenset(
    {
        "password",
        "passwd",
        "pwd",
        "secret",
        "token",
        "access_token",
        "refresh_token",
        "id_token",
        "jwt",
        "authorization",
        "auth",
        "cookie",
        "set-cookie",
        "session_token",
        "api_key",
        "apikey",
        "client_secret",
        "private_key",
        "mfa",
        "mfa_secret",
        "totp",
        "otp",
        "hashed_password",
        "credential",
        "credentials",
        "otp_code",
    }
)

REDACTED = "[redacted]"

#: Key fragments that also mark a value as sensitive.
_SENSITIVE_FRAGMENTS = ("password", "secret", "token", "jwt", "credential", "apikey", "api_key")

logger = logging.getLogger(SECURITY_LOGGER_NAME)

_file_lock = threading.Lock()


def _ensure_logger_enabled() -> logging.Logger:
    """Make sure the security logger can emit.

    Some third-party libraries (for example Streamlit) call
    ``logging.config.dictConfig(..., disable_existing_loggers=True)`` on import,
    which disables every logger that already existed. The security event
    stream must not disappear because of that, so the logger is re-enabled
    before each event.
    """
    if logger.disabled:
        logger.disabled = False
    return logger


def _is_sensitive_key(key: str) -> bool:
    lowered = str(key).lower()
    if lowered in SENSITIVE_KEYS:
        return True
    return any(fragment in lowered for fragment in _SENSITIVE_FRAGMENTS)


def redact(value: Any, _depth: int = 0) -> Any:
    """Recursively redact sensitive values from a payload.

    Dictionaries lose the sensitive entries, sequences are cleaned element by
    element and strings are only redacted when they arrive under a sensitive
    key (a bare string can legitimately be an opaque but harmless value).
    """
    if _depth > 6:
        return REDACTED
    if isinstance(value, Mapping):
        cleaned: Dict[str, Any] = {}
        for key, item in value.items():
            if _is_sensitive_key(str(key)):
                cleaned[str(key)] = REDACTED
            else:
                cleaned[str(key)] = redact(item, _depth + 1)
        return cleaned
    if isinstance(value, (list, tuple, set)):
        return [redact(item, _depth + 1) for item in value]
    if isinstance(value, (bytes, bytearray)):
        return REDACTED
    return value


@dataclass
class SecurityEvent:
    """A single structured security event."""

    event_type: str
    severity: str = "info"
    outcome: str = "failure"
    actor_id: Optional[str] = None
    ip_address: Optional[str] = None
    request_id: Optional[str] = None
    path: Optional[str] = None
    method: Optional[str] = None
    details: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        payload: Dict[str, Any] = {
            "event_type": self.event_type,
            "severity": self.severity,
            "outcome": self.outcome,
            "timestamp": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "request_id": self.request_id or get_request_id() or None,
        }
        if self.actor_id:
            payload["actor_id"] = self.actor_id
        if self.ip_address:
            payload["ip_address"] = self.ip_address
        if self.path:
            payload["path"] = self.path
        if self.method:
            payload["method"] = self.method
        if self.details:
            payload["details"] = redact(self.details)
        return payload


def _event_file_path() -> Optional[str]:
    path = os.getenv("SECURITY_EVENT_LOG_FILE", "").strip()
    return path or None


def log_security_event(
    event_type: str,
    *,
    severity: str = "info",
    outcome: str = "failure",
    actor_id: Optional[str] = None,
    ip_address: Optional[str] = None,
    request_id: Optional[str] = None,
    path: Optional[str] = None,
    method: Optional[str] = None,
    details: Optional[Mapping[str, Any]] = None,
) -> SecurityEvent:
    """Emit a structured security event.

    The event is written to the dedicated security logger and, when
    ``SECURITY_EVENT_LOG_FILE`` is configured, appended as one JSON line to that
    file as well.
    """
    event = SecurityEvent(
        event_type=event_type,
        severity=severity,
        outcome=outcome,
        actor_id=actor_id,
        ip_address=ip_address,
        request_id=request_id,
        path=path,
        method=method,
        details=dict(details or {}),
    )
    payload = event.to_dict()
    line = json.dumps(payload, sort_keys=True, default=str)

    _ensure_logger_enabled().log(
        {
            "critical": logging.CRITICAL,
            "error": logging.ERROR,
            "warning": logging.WARNING,
            "info": logging.INFO,
            "debug": logging.DEBUG,
        }.get(severity.lower(), logging.INFO),
        line,
    )

    target = _event_file_path()
    if target:
        try:
            with _file_lock:
                with open(target, "a", encoding="utf-8") as handle:
                    handle.write(line + "\n")
        except Exception as exc:  # pragma: no cover - defensive
            logger.warning("Could not append security event to %s: %s", target, exc)

    return event
