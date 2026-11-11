"""Honeypot (decoy) records.

Decoys are identifiers that look like master data but exist only in the
dedicated ``security_decoys`` table. They are:

* **never** inserted into ``students``, ``attendance`` or ``sessions``;
* **never** part of the AI query tools' allowed tables, so they cannot appear
  in a normal assistant answer;
* only active when the deployment explicitly enables them
  (``SECURITY_DECOY_MODE=log``), so a default deployment has no decoys at all;
* probed on identifier lookups - a hit produces a security event and the same
  "not found" answer as a genuinely unknown identifier, so a prober cannot
  distinguish a decoy from a non-existent record.
"""

from __future__ import annotations

import logging
import os
import sqlite3
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import SecurityDecoy
from app.security.detection import detector

logger = logging.getLogger("rollcall.security.decoys")

#: Modes: "off" (default), "log" (probe and report), "enforce" (also reject).
DECOY_MODE_ENV = "SECURITY_DECOY_MODE"

MODE_OFF = "off"
MODE_LOG = "log"
MODE_ENFORCE = "enforce"


def decoy_mode() -> str:
    """Return the configured decoy mode (off by default)."""
    mode = os.getenv(DECOY_MODE_ENV, MODE_OFF).strip().lower()
    return mode if mode in (MODE_OFF, MODE_LOG, MODE_ENFORCE) else MODE_OFF


def decoys_enabled() -> bool:
    """True when decoy probing is enabled by configuration."""
    return decoy_mode() != MODE_OFF


def create_decoy(
    db: Session,
    *,
    decoy_kind: str,
    decoy_value: str,
    note: Optional[str] = None,
    created_by: Optional[str] = None,
) -> Dict[str, Any]:
    """Register a decoy identifier (ADMIN only endpoint)."""
    clean_kind = str(decoy_kind).strip().upper()
    clean_value = str(decoy_value).strip().upper()
    if not clean_kind or not clean_value:
        raise ValueError("A decoy needs both a kind and a value.")
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    decoy = SecurityDecoy(
        decoy_kind=clean_kind,
        decoy_value=clean_value,
        enabled=1,
        note=note,
        created_by=created_by,
        created_at=now,
    )
    db.add(decoy)
    db.flush()
    return {
        "id": decoy.id,
        "decoy_kind": decoy.decoy_kind,
        "decoy_value": decoy.decoy_value,
        "enabled": decoy.enabled,
        "note": decoy.note,
        "created_at": decoy.created_at,
    }


def list_decoys(db: Session) -> List[Dict[str, Any]]:
    """List the registered decoys (ADMIN only endpoint)."""
    rows = db.execute(select(SecurityDecoy).order_by(SecurityDecoy.id)).scalars().all()
    return [
        {
            "id": row.id,
            "decoy_kind": row.decoy_kind,
            "decoy_value": row.decoy_value,
            "enabled": row.enabled,
            "note": row.note,
            "created_at": row.created_at,
        }
        for row in rows
    ]


def _lookup(db: Any, value: str) -> Optional[Dict[str, Any]]:
    try:
        if isinstance(db, Session):
            row = db.execute(
                select(SecurityDecoy).where(
                    SecurityDecoy.decoy_value == value,
                    SecurityDecoy.enabled == 1,
                )
            ).scalars().first()
            return {"decoy_kind": row.decoy_kind} if row is not None else None
        cursor = db.execute(
            "SELECT decoy_kind FROM security_decoys WHERE decoy_value = ? AND enabled = 1 LIMIT 1",
            (value,),
        ).fetchone()
        return {"decoy_kind": cursor[0]} if cursor else None
    except Exception:
        # A missing decoy table simply means there are no decoys.
        return None


def probe_decoy(
    db: Any,
    value: Optional[str],
    *,
    actor_id: Optional[str] = None,
    ip_address: Optional[str] = None,
    request_id: Optional[str] = None,
    path: Optional[str] = None,
) -> bool:
    """Check whether an identifier is a decoy; report it as a security event.

    Returns True when the value is a decoy. Decoys are only probed when the
    deployment enabled them, so the default behaviour is unchanged.
    """
    if not value or not decoys_enabled():
        return False
    clean = str(value).strip().upper()
    if not clean:
        return False
    hit = _lookup(db, clean)
    if not hit:
        return False
    detector.record_decoy_probe(
        decoy_kind=str(hit.get("decoy_kind") or "UNKNOWN"),
        actor_id=actor_id,
        ip_address=ip_address,
        request_id=request_id,
        path=path,
    )
    return True
