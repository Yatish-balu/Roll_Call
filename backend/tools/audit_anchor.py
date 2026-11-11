"""Off-database signed anchor for the audit hash chain.

Publishing the chain head to a location *outside* the database turns the chain
from "internally consistent" into "anchored": an attacker who rewrites the
database cannot forge the anchor file without the HMAC secret.

Usage::

    python -m tools.audit_anchor --db data/attendance.db --output-dir ./audit-anchors

The anchor file is a JSON document containing the chain head and an HMAC
signature over it. Scheduling it daily (cron / systemd timer / CI job) is an
operational task for the deployment owner; this module only produces the
signed artefact.

The HMAC secret is read from the environment (``AUDIT_CHAIN_HMAC_SECRET``)
and is never written to the anchor file.
"""

from __future__ import annotations

import argparse
import hashlib
import hmac
import json
import os
import sqlite3
import sys
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app.security.audit_chain import (  # noqa: E402
    DEFAULT_CHAIN_ID,
    get_chain_secret,
)


def read_chain_head(db_path: str, chain_id: str) -> Optional[Dict[str, Any]]:
    """Read the current head of a chain from the database (read-only)."""
    conn = sqlite3.connect(f"file:{os.path.abspath(db_path)}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    try:
        try:
            row = conn.execute(
                "SELECT chain_id, last_hash, last_log_id, updated_at FROM audit_chain_head "
                "WHERE chain_id = ?",
                (chain_id,),
            ).fetchone()
        except sqlite3.Error:
            return None
        return dict(row) if row else None
    finally:
        conn.close()


def build_anchor(head: Dict[str, Any], secret: bytes) -> Dict[str, Any]:
    """Build the signed anchor document for a chain head."""
    payload = {
        "chain_id": head.get("chain_id"),
        "last_log_id": head.get("last_log_id"),
        "last_hash": head.get("last_hash"),
        "head_updated_at": head.get("updated_at"),
        "anchored_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    }
    canonical = "\x1f".join(f"{key}={payload[key]}" for key in sorted(payload))
    signature = hmac.new(secret, canonical.encode("utf-8"), hashlib.sha256).hexdigest()
    payload["signature"] = signature
    payload["signature_algorithm"] = "HMAC-SHA256"
    return payload


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description="Write a signed, off-database anchor for the audit hash chain."
    )
    parser.add_argument("--db", required=True, help="Path to the SQLite database")
    parser.add_argument("--chain", default=DEFAULT_CHAIN_ID, help="Chain identifier")
    parser.add_argument(
        "--output-dir",
        required=True,
        help="Directory outside the database where the anchor file is written",
    )
    args = parser.parse_args(argv)

    secret = get_chain_secret()
    if secret is None:
        print(
            "AUDIT_CHAIN_HMAC_SECRET is not provisioned; no anchor can be signed.",
            file=sys.stderr,
        )
        return 2

    head = read_chain_head(args.db, args.chain)
    if not head:
        print(f"No chain head found for chain '{args.chain}'.", file=sys.stderr)
        return 2

    anchor = build_anchor(head, secret)
    os.makedirs(args.output_dir, exist_ok=True)
    stamp = anchor["anchored_at"].replace(":", "").replace("-", "")
    path = os.path.join(args.output_dir, f"audit-anchor-{args.chain}-{stamp}.json")
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(anchor, handle, indent=2, sort_keys=True)
    print(path)
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
