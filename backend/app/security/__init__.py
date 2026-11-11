"""Security engineering modules for RollCall AI.

This package contains the security *operational* layer:

* ``events``    - structured security event logging (separate from the
                  application audit log, which stays in the database).
* ``context``   - request correlation ids.
* ``detection`` - suspicious-activity detection foundations (IDS).
* ``decoys``    - honeypot records that never touch real master data.
* ``audit_chain`` - canonical serialisation and HMAC hashing for the
                  append-only audit hash chain.
"""

from app.security.context import (
    clear_request_id,
    get_request_id,
    set_request_id,
)
from app.security.events import (
    SENSITIVE_KEYS,
    SecurityEvent,
    log_security_event,
    redact,
)

__all__ = [
    "SENSITIVE_KEYS",
    "SecurityEvent",
    "clear_request_id",
    "get_request_id",
    "log_security_event",
    "redact",
    "set_request_id",
]
