"""Standalone verification of the audit hash chain.

Usage::

    python -m tools.verify_audit_chain --db data/attendance.db
    python -m tools.verify_audit_chain --db data/attendance.db --json

The command is read-only. It detects missing, modified, reordered and invalid
records. Records written before the chain was activated are reported as
*unverified* - they are never claimed to be cryptographically verified, and a
chain without an external anchor only proves internal consistency.

Exit codes:
    0  the chain is intact (or only contains unverified legacy records)
    1  tampering detected
    2  the chain could not be verified (no HMAC secret provisioned)
"""

from __future__ import annotations

import argparse
import json
import os
import sqlite3
import sys
from typing import Any, Dict, List, Optional

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app.security.audit_chain import (  # noqa: E402
    CHAIN_SECRET_ENV,
    DEFAULT_CHAIN_ID,
    get_chain_secret,
    verify_chain,
)

AUDIT_COLUMNS = (
    "log_id",
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
    "chain_id",
    "prev_hash",
    "row_hash",
)


def _has_chain_columns(conn: sqlite3.Connection) -> bool:
    try:
        columns = {row[1] for row in conn.execute("PRAGMA table_info(audit_log)")}
    except sqlite3.Error:
        return False
    return {"chain_id", "prev_hash", "row_hash"}.issubset(columns)


def _read_rows(db_path: str, chain_id: str) -> List[Dict[str, Any]]:
    conn = sqlite3.connect(f"file:{os.path.abspath(db_path)}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    try:
        try:
            conn.execute("SELECT 1 FROM audit_log LIMIT 1").fetchall()
        except sqlite3.Error as exc:
            raise LookupError(f"The database has no readable audit_log table: {exc}") from exc
        if not _has_chain_columns(conn):
            select_columns = (
                "log_id, actor_id, action, session_id, usn, entity_type, entity_id, "
                "old_value, new_value, reason, timestamp, NULL AS actor_role, "
                "NULL AS chain_id, NULL AS prev_hash, NULL AS row_hash"
            )
        else:
            select_columns = ", ".join(AUDIT_COLUMNS)
        rows = conn.execute(
            f"SELECT {select_columns} FROM audit_log "  # nosec B608 - select_columns is a constant string
            "WHERE chain_id IS NULL OR chain_id = ? ORDER BY log_id ASC",
            (chain_id,),
        ).fetchall()
        return [dict(row) for row in rows]
    finally:
        conn.close()


def _format_report(result: Dict[str, Any], db_path: str) -> str:
    lines = [
        "RollCall AI - audit chain verification",
        f"database: {db_path}",
        "",
        f"records inspected      : {result['total_records']}",
        f"chained records        : {result['chained_records']}",
        f"verified records       : {result['verified_records']}",
        f"legacy (unverified)    : {result['legacy_records']}",
        f"modified records       : {len(result['modified_records'])} {result['modified_records']}",
        f"missing records        : {len(result['missing_records'])} {result['missing_records']}",
        f"reordered records      : {len(result['reordered_records'])} {result['reordered_records']}",
        f"invalid hmac records   : {len(result['invalid_hmac_records'])} {result['invalid_hmac_records']}",
        f"chain break at log_id  : {result['chain_break_at']}",
        f"externally anchored    : {result['externally_anchored']}",
        "",
    ]
    if result["legacy_records"]:
        lines.append(
            "NOTE: records without a chain hash were written before the hash chain was"
        )
        lines.append(
            "      activated. They are reported as UNVERIFIED and are never claimed to be"
        )
        lines.append("      cryptographically verified.")
        lines.append("")
    if not result["externally_anchored"]:
        lines.append(
            "NOTE: no external anchor was configured. The chain proves internal"
        )
        lines.append(
            "      consistency only; an off-database signed digest is required for"
        )
        lines.append(
            "      stronger tamper evidence (see tools/audit_anchor.py)."
        )
        lines.append("")
    for message in result.get("errors", []):
        lines.append(f"ERROR: {message}")
    lines.append("RESULT: " + ("INTACT" if result["ok"] else "TAMPERING DETECTED"))
    return "\n".join(lines)


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description="Verify the append-only audit hash chain of a RollCall AI database."
    )
    parser.add_argument("--db", required=True, help="Path to the SQLite database to verify")
    parser.add_argument("--chain", default=DEFAULT_CHAIN_ID, help="Chain identifier to verify")
    parser.add_argument("--json", action="store_true", help="Emit the report as JSON")
    args = parser.parse_args(argv)

    if not os.path.exists(args.db):
        print(f"Database not found: {args.db}", file=sys.stderr)
        return 2

    secret = get_chain_secret()
    if secret is None:
        print(
            f"WARNING: {CHAIN_SECRET_ENV} is not provisioned; chained records cannot be "
            "cryptographically verified.",
            file=sys.stderr,
        )

    try:
        rows = _read_rows(args.db, args.chain)
    except LookupError as exc:
        print(f"Cannot verify the audit chain: {exc}", file=sys.stderr)
        return 2
    result = verify_chain(rows, secret=secret, chain_id=args.chain).to_dict()

    if args.json:
        print(json.dumps(result, indent=2, sort_keys=True, default=str))
    else:
        print(_format_report(result, args.db))

    if not result["ok"]:
        try:
            from app.security.events import log_security_event

            log_security_event(
                "audit_chain_verification_failed",
                severity="critical",
                outcome="failure",
                details={
                    "database": os.path.abspath(args.db),
                    "modified_records": result["modified_records"],
                    "missing_records": result["missing_records"],
                    "reordered_records": result["reordered_records"],
                    "invalid_hmac_records": result["invalid_hmac_records"],
                },
            )
        except Exception:  # pragma: no cover - defensive
            pass
        return 1

    return 2 if secret is None else 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
