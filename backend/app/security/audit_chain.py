"""Append-only cryptographic hash chain for the application audit log.

Every audit record can carry the HMAC-SHA256 hash of its canonical
serialisation and the hash of its predecessor. Any modification, deletion or
reordering of a chained record breaks the linkage and is detected by the
standalone verifier (``tools/verify_audit_chain.py``).

Design notes
------------
* The canonical form is a deterministic ``\\x1f``-separated list of
  ``field=value`` pairs. ``None`` is serialised as the empty string so that a
  missing value and an empty value cannot be confused after tampering.
* The HMAC secret is read from the environment (``AUDIT_CHAIN_HMAC_SECRET``)
  and is *never* stored in the database, logged or written to a file by this
  module. When the secret is not provisioned the chain stays disabled and
  records are written without hashes (they are then reported as unverified).
* ``log_id`` is deliberately **not** part of the canonical payload: the row
  cannot be updated afterwards (the audit log is append-only), so the hash must
  be computable before the insert. The position of a record is protected by
  the ``prev_hash`` linkage instead.
"""

from __future__ import annotations

import hashlib
import hmac
import os
from dataclasses import dataclass
from typing import Any, Dict, List, Mapping, Optional, Sequence

#: Canonical field order of an audit record. The order is part of the
#: contract: changing it invalidates every existing hash.
CANONICAL_FIELDS: Sequence[str] = (
    "chain_id",
    "actor_id",
    "actor_role",
    "action",
    "session_id",
    "usn",
    "entity_type",
    "entity_id",
    "old_value",
    "new_value",
    "reason",
    "timestamp",
    "prev_hash",
)

#: Separator between canonical fields (ASCII unit separator).
FIELD_SEPARATOR = "\x1f"

#: The chain identifier used when nothing else is configured.
DEFAULT_CHAIN_ID = "default"

#: Value of ``prev_hash`` for the first record of a chain. It is a *starting
#: point*, not a trusted anchor: without an external signed digest the chain
#: can only prove internal consistency.
GENESIS_HASH = "GENESIS"

#: Environment variable holding the HMAC secret (provisioned by the DB owner).
CHAIN_SECRET_ENV = "AUDIT_CHAIN_HMAC_SECRET"

#: Environment variable holding an optional external anchor value.
CHAIN_ANCHOR_ENV = "AUDIT_CHAIN_GENESIS_ANCHOR"

#: Minimum acceptable HMAC secret length (defence against weak keys).
MIN_SECRET_LENGTH = 32


def get_chain_secret() -> Optional[bytes]:
    """Return the configured HMAC secret, or None when the chain is disabled.

    The secret is read from the environment only. It is never logged, never
    persisted and never returned to a client.
    """
    raw = os.getenv(CHAIN_SECRET_ENV, "")
    if not raw or len(raw.strip()) < MIN_SECRET_LENGTH:
        return None
    return raw.strip().encode("utf-8")


def chain_enabled() -> bool:
    """True when a usable HMAC secret is provisioned."""
    return get_chain_secret() is not None


def get_genesis_hash() -> str:
    """Return the first link of a chain.

    When the operator provisions ``AUDIT_CHAIN_GENESIS_ANCHOR`` that value is
    the externally trusted starting point. Without it the chain starts at the
    well-known ``GENESIS`` marker, which proves internal consistency only.
    """
    anchor = os.getenv(CHAIN_ANCHOR_ENV, "").strip()
    return anchor or GENESIS_HASH


def canonical_audit_payload(data: Mapping[str, Any]) -> str:
    """Build the canonical serialisation of an audit record."""
    parts: List[str] = []
    for field in CANONICAL_FIELDS:
        value = data.get(field)
        if value is None:
            value = ""
        parts.append(f"{field}={value}")
    return FIELD_SEPARATOR.join(parts)


def compute_row_hash(data: Mapping[str, Any], secret: bytes) -> str:
    """Compute the HMAC-SHA256 hash of a record's canonical serialisation."""
    payload = canonical_audit_payload(data)
    return hmac.new(secret, payload.encode("utf-8"), hashlib.sha256).hexdigest()


def row_hash_matches(data: Mapping[str, Any], secret: bytes) -> bool:
    """Constant-time comparison of a record's stored hash with its computed hash."""
    stored = str(data.get("row_hash") or "")
    if not stored:
        return False
    expected = compute_row_hash(data, secret)
    return hmac.compare_digest(stored, expected)


def chain_payload_from_row(row: Mapping[str, Any]) -> Dict[str, Any]:
    """Project an audit row onto the canonical fields."""
    return {
        "chain_id": row.get("chain_id") or DEFAULT_CHAIN_ID,
        "actor_id": row.get("actor_id"),
        "actor_role": row.get("actor_role"),
        "action": row.get("action"),
        "session_id": row.get("session_id"),
        "usn": row.get("usn"),
        "entity_type": row.get("entity_type"),
        "entity_id": row.get("entity_id"),
        "old_value": row.get("old_value"),
        "new_value": row.get("new_value"),
        "reason": row.get("reason"),
        "timestamp": row.get("timestamp"),
        "prev_hash": row.get("prev_hash"),
    }


@dataclass
class ChainVerificationResult:
    """Outcome of verifying one audit chain."""

    total_records: int = 0
    chained_records: int = 0
    legacy_records: int = 0
    verified_records: int = 0
    modified_records: List[int] = None  # type: ignore[assignment]
    missing_records: List[int] = None  # type: ignore[assignment]
    reordered_records: List[int] = None  # type: ignore[assignment]
    invalid_hmac_records: List[int] = None  # type: ignore[assignment]
    chain_break_at: Optional[int] = None
    externally_anchored: bool = False
    secret_configured: bool = True
    errors: List[str] = None  # type: ignore[assignment]

    @property
    def ok(self) -> bool:
        """True when no tampering was detected."""
        return not (
            self.modified_records
            or self.missing_records
            or self.reordered_records
            or self.invalid_hmac_records
        )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "ok": self.ok,
            "total_records": self.total_records,
            "chained_records": self.chained_records,
            "legacy_records": self.legacy_records,
            "verified_records": self.verified_records,
            "modified_records": list(self.modified_records or []),
            "missing_records": list(self.missing_records or []),
            "reordered_records": list(self.reordered_records or []),
            "invalid_hmac_records": list(self.invalid_hmac_records or []),
            "chain_break_at": self.chain_break_at,
            "externally_anchored": self.externally_anchored,
            "secret_configured": self.secret_configured,
            "errors": list(self.errors or []),
        }


def verify_chain(
    rows: Sequence[Mapping[str, Any]],
    *,
    secret: Optional[bytes] = None,
    chain_id: str = DEFAULT_CHAIN_ID,
) -> ChainVerificationResult:
    """Verify the integrity of an audit chain.

    ``rows`` must be the audit records of one chain in ``log_id`` order.

    The result distinguishes:

    * ``legacy_records`` - records written before the chain was activated.
      They are reported as *unverified*; they are never claimed to be
      cryptographically verified.
    * ``modified_records`` - the stored hash does not match the record content.
    * ``invalid_hmac_records`` - the stored hash is not a valid HMAC value.
    * ``missing_records`` - a gap in the record sequence.
    * ``reordered_records`` - the predecessor linkage does not match.
    """
    result = ChainVerificationResult(
        modified_records=[],
        missing_records=[],
        reordered_records=[],
        invalid_hmac_records=[],
        errors=[],
    )
    result.total_records = len(rows)
    result.secret_configured = secret is not None
    result.externally_anchored = bool(os.getenv(CHAIN_ANCHOR_ENV, "").strip())

    if secret is None:
        result.errors.append(
            "No HMAC secret configured: chained records cannot be cryptographically verified."
        )

    expected_prev = get_genesis_hash()
    previous_log_id: Optional[int] = None
    previous_row_hash: Optional[str] = None

    for row in rows:
        log_id = row.get("log_id")
        row_hash = row.get("row_hash")
        prev_hash = row.get("prev_hash")

        if row_hash is None or prev_hash is None:
            # Legacy record: written before the chain was activated.
            result.legacy_records += 1
            previous_log_id = log_id
            previous_row_hash = row_hash
            expected_prev = row_hash or expected_prev
            continue

        result.chained_records += 1

        # 1. Sequence continuity (a missing record shows up as a gap).
        if previous_log_id is not None and isinstance(log_id, int) and isinstance(previous_log_id, int):
            if log_id != previous_log_id + 1:
                for gap in range(previous_log_id + 1, log_id):
                    result.missing_records.append(gap)

        # 2. Predecessor linkage (detects reordering and removals).
        if prev_hash != expected_prev:
            result.reordered_records.append(log_id)
            if result.chain_break_at is None:
                result.chain_break_at = log_id

        # 3. Content integrity.
        if secret is not None:
            payload = chain_payload_from_row(row)
            computed = compute_row_hash(payload, secret)
            if len(str(row_hash)) != 64 or not all(
                char in "0123456789abcdef" for char in str(row_hash).lower()
            ):
                result.invalid_hmac_records.append(log_id)
            elif not hmac.compare_digest(str(row_hash), computed):
                result.modified_records.append(log_id)
            else:
                result.verified_records += 1
        else:
            result.errors.append(
                f"Record {log_id} could not be verified (no HMAC secret configured)."
            )

        previous_log_id = log_id
        previous_row_hash = str(row_hash)
        expected_prev = str(row_hash)

    return result
