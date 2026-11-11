"""Security phase 3 tests: audit hash chain, security events, detection, decoys, CI.

Covers:
  * hash-chain integrity (intact chain, modified record, missing record,
    reordered record, invalid HMAC, legacy records);
  * transactional chain updates and concurrent audit writes;
  * security event redaction (no passwords, tokens or credentials);
  * detection thresholds (events fire at the threshold, never on a single event);
  * decoy behaviour (disabled by default, never mixed with real data);
  * the CI workflow configuration.
"""

from __future__ import annotations

import json
import os
import re
import sqlite3
import subprocess
import sys
import tempfile
import threading
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from sqlalchemy import create_engine, select, text
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session as OrmSession, sessionmaker
from sqlalchemy.pool import StaticPool

from app.db.base import Base
from app.db import crud
import app.db.models as models
from app.security import audit_chain, detection, events
from app.security.detection import DetectionThresholds, SecurityDetector

TEST_SECRET = "test-secret-key-for-security-phase3-at-least-32-chars"
CHAIN_SECRET = "phase3-chain-hmac-secret-value-0123456789abcdef"
BACKEND_DIR = Path(__file__).resolve().parents[1]
REPO_ROOT = BACKEND_DIR.parent


@pytest.fixture
def chain_env(monkeypatch):
    monkeypatch.setenv("AUDIT_CHAIN_HMAC_SECRET", CHAIN_SECRET)
    monkeypatch.delenv("AUDIT_CHAIN_GENESIS_ANCHOR", raising=False)
    yield


@pytest.fixture
def db_env():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, class_=OrmSession, expire_on_commit=False)
    with factory() as db:
        db.add(
            models.User(
                user_id="admin_root",
                email="admin_root@rollcall.edu",
                role="ADMIN",
                hashed_password=None,
                is_active=1,
                created_at="2026-01-01T00:00:00Z",
            )
        )
        db.commit()
    yield factory
    engine.dispose()


def _write(factory, action="ATTENDANCE_UPSERT", **kwargs):
    with factory() as db:
        entry = crud.create_audit_entry(
            db,
            actor_id=kwargs.pop("actor_id", "admin_root"),
            actor_role=kwargs.pop("actor_role", "ADMIN"),
            action=action,
            entity_type="attendance",
            entity_id=kwargs.pop("entity_id", "ATT-1"),
            session_id=kwargs.pop("session_id", "SESS-1"),
            usn=kwargs.pop("usn", "1MS21CS001"),
            old_value=kwargs.pop("old_value", "PRESENT"),
            new_value=kwargs.pop("new_value", "ABSENT"),
            **kwargs,
        )
        db.commit()
        return entry


def _rows(factory):
    with factory() as db:
        return [
            dict(row)
            for row in db.execute(text("SELECT * FROM audit_log ORDER BY log_id ASC")).mappings().all()
        ]


# ---------------------------------------------------------------------------
# 1. Hash chain integrity
# ---------------------------------------------------------------------------

def test_chain_records_are_linked_and_verifiable(chain_env, db_env):
    _write(db_env)
    _write(db_env, action="ATTENDANCE_BULK_UPSERT", entity_id="ATT-2")
    _write(db_env, action="SESSION_CREATE", entity_id="SESS-1")

    rows = _rows(db_env)
    assert len(rows) == 3
    assert rows[0]["prev_hash"] == audit_chain.GENESIS_HASH
    assert rows[1]["prev_hash"] == rows[0]["row_hash"]
    assert rows[2]["prev_hash"] == rows[1]["row_hash"]
    assert all(row["row_hash"] for row in rows)

    result = audit_chain.verify_chain(rows, secret=CHAIN_SECRET.encode())
    assert result.ok is True
    assert result.verified_records == 3
    assert result.modified_records == []


def test_chain_head_advances_with_the_records(chain_env, db_env):
    _write(db_env)
    _write(db_env, entity_id="ATT-2")
    with db_env() as db:
        head = db.get(models.AuditChainHead, audit_chain.DEFAULT_CHAIN_ID)
        assert head is not None
        assert head.last_log_id == 2
        assert head.last_hash == _rows(db_env)[-1]["row_hash"]


def test_modified_record_is_detected(chain_env, db_env):
    _write(db_env)
    _write(db_env, entity_id="ATT-2")
    rows = _rows(db_env)

    # Tamper with the stored content (as an attacker with DB access would).
    rows[0]["new_value"] = "PRESENT"
    result = audit_chain.verify_chain(rows, secret=CHAIN_SECRET.encode())
    assert result.ok is False
    assert result.modified_records == [rows[0]["log_id"]]


def test_missing_record_is_detected(chain_env, db_env):
    _write(db_env)
    _write(db_env, entity_id="ATT-2")
    _write(db_env, entity_id="ATT-3")
    rows = _rows(db_env)
    del rows[1]
    result = audit_chain.verify_chain(rows, secret=CHAIN_SECRET.encode())
    assert result.ok is False
    assert result.missing_records or result.reordered_records


def test_reordered_record_is_detected(chain_env, db_env):
    _write(db_env)
    _write(db_env, entity_id="ATT-2")
    _write(db_env, entity_id="ATT-3")
    rows = _rows(db_env)
    rows[1], rows[2] = rows[2], rows[1]
    result = audit_chain.verify_chain(rows, secret=CHAIN_SECRET.encode())
    assert result.ok is False
    assert result.reordered_records


def test_invalid_hmac_is_detected(chain_env, db_env):
    _write(db_env)
    rows = _rows(db_env)
    rows[0]["row_hash"] = "not-a-hash"
    result = audit_chain.verify_chain(rows, secret=CHAIN_SECRET.encode())
    assert result.ok is False
    assert result.invalid_hmac_records == [rows[0]["log_id"]]


def test_wrong_secret_invalidates_the_chain(chain_env, db_env):
    _write(db_env)
    _write(db_env, entity_id="ATT-2")
    rows = _rows(db_env)
    result = audit_chain.verify_chain(rows, secret=b"a-completely-different-secret-value")
    assert result.ok is False
    assert result.modified_records


def test_legacy_records_are_reported_as_unverified(chain_env, db_env):
    """Records written before the chain was activated are never 'verified'."""
    with db_env() as db:
        db.execute(
            text(
                "INSERT INTO audit_log (actor_id, actor_role, action, session_id, usn, "
                "entity_type, entity_id, old_value, new_value, reason, timestamp) "
                "VALUES ('admin_root', 'ADMIN', 'LEGACY_ACTION', NULL, NULL, 'attendance', "
                "'ATT-LEGACY', NULL, NULL, NULL, '2020-01-01T00:00:00Z')"
            )
        )
        db.commit()
    _write(db_env)

    rows = _rows(db_env)
    result = audit_chain.verify_chain(rows, secret=CHAIN_SECRET.encode())
    assert result.legacy_records == 1
    assert result.verified_records == 1
    # The legacy record is not counted as verified.
    assert result.verified_records + result.legacy_records == result.total_records


def test_chain_is_disabled_without_a_secret(monkeypatch, db_env):
    monkeypatch.delenv("AUDIT_CHAIN_HMAC_SECRET", raising=False)
    entry = _write(db_env)
    assert entry["row_hash"] is None
    assert entry["prev_hash"] is None
    rows = _rows(db_env)
    assert all(row["row_hash"] is None for row in rows)
    result = audit_chain.verify_chain(rows, secret=None)
    assert result.secret_configured is False
    assert result.errors


def test_canonical_payload_is_deterministic_and_field_complete():
    data = {
        "chain_id": "default",
        "actor_id": "u1",
        "actor_role": "FACULTY",
        "action": "ATTENDANCE_UPSERT",
        "session_id": "S1",
        "usn": "U1",
        "entity_type": "attendance",
        "entity_id": "E1",
        "old_value": "PRESENT",
        "new_value": "ABSENT",
        "reason": None,
        "timestamp": "2026-01-01T00:00:00Z",
        "prev_hash": "GENESIS",
    }
    first = audit_chain.canonical_audit_payload(data)
    second = audit_chain.canonical_audit_payload(dict(data))
    assert first == second
    for field in ("actor_id", "actor_role", "action", "session_id", "usn", "old_value", "new_value", "timestamp"):
        assert field in first
    # A changed field changes the canonical form.
    assert audit_chain.canonical_audit_payload({**data, "new_value": "PRESENT"}) != first


def test_concurrent_audit_writes_keep_the_chain_consistent(chain_env, tmp_path):
    """Parallel writers must not fork the chain.

    A file-backed SQLite database gives every thread its own connection (an
    in-memory StaticPool would share one). A writer that loses the SQLite
    write lock fails as a whole - the attendance change and its audit record
    share the transaction, so nothing is ever written unaudited.
    """
    db_path = tmp_path / "concurrent.db"
    engine = create_engine(
        f"sqlite:///{db_path.as_posix()}",
        connect_args={"check_same_thread": False, "timeout": 30},
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, class_=OrmSession, expire_on_commit=False)
    with factory() as db:
        db.add(
            models.User(
                user_id="admin_root",
                email="admin_root@rollcall.edu",
                role="ADMIN",
                hashed_password=None,
                is_active=1,
                created_at="2026-01-01T00:00:00Z",
            )
        )
        db.commit()

    written = []
    errors = []

    def writer(index: int) -> None:
        for attempt in range(3):
            try:
                with factory() as db:
                    entry = crud.create_audit_entry(
                        db,
                        actor_id="admin_root",
                        actor_role="ADMIN",
                        action="ATTENDANCE_UPSERT",
                        entity_type="attendance",
                        entity_id=f"ATT-{index}",
                        old_value="PRESENT",
                        new_value="ABSENT",
                    )
                    db.commit()
                    written.append(entry)
                return
            except OperationalError as exc:  # pragma: no cover - timing dependent
                errors.append(str(exc))
                time.sleep(0.2)
            except Exception as exc:  # pragma: no cover
                errors.append(str(exc))
                return

    threads = [threading.Thread(target=writer, args=(i,)) for i in range(5)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    with factory() as db:
        rows = [
            dict(row)
            for row in db.execute(text("SELECT * FROM audit_log ORDER BY log_id ASC")).mappings().all()
        ]
    engine.dispose()

    assert written, "no audit record could be written"
    assert len(rows) == len(written), "an audit record was persisted without being returned"
    # Whatever the interleaving was, the chain must be a single chain.
    result = audit_chain.verify_chain(rows, secret=CHAIN_SECRET.encode())
    assert result.ok is True, result.to_dict()
    assert result.modified_records == []
    assert result.reordered_records == []


# ---------------------------------------------------------------------------
# 2. Security event logging
# ---------------------------------------------------------------------------

def test_security_event_redacts_secrets():
    payload = {
        "password": "hunter2",
        "token": "abc.def.ghi",
        "refresh_token": "rt-123",
        "authorization": "Bearer abc",
        "mfa_secret": "123456",
        "hashed_password": "hash",
        "nested": {"api_key": "k", "safe": "value"},
        "list": [{"client_secret": "s"}],
    }
    cleaned = events.redact(payload)
    assert cleaned["password"] == events.REDACTED
    assert cleaned["token"] == events.REDACTED
    assert cleaned["refresh_token"] == events.REDACTED
    assert cleaned["authorization"] == events.REDACTED
    assert cleaned["mfa_secret"] == events.REDACTED
    assert cleaned["hashed_password"] == events.REDACTED
    assert cleaned["nested"]["api_key"] == events.REDACTED
    assert cleaned["nested"]["safe"] == "value"
    assert cleaned["list"][0]["client_secret"] == events.REDACTED


def test_security_event_is_structured_json_and_never_leaks_secrets(caplog):
    with caplog.at_level("INFO", logger=events.SECURITY_LOGGER_NAME):
        event = events.log_security_event(
            "authentication_failed",
            severity="warning",
            actor_id="u1",
            ip_address="203.0.113.9",
            request_id="req-123",
            path="/api/v1/auth/login",
            method="POST",
            details={"password": "hunter2", "user_id": "u1"},
        )
    assert event.to_dict()["event_type"] == "authentication_failed"
    records = [r for r in caplog.records if r.name == events.SECURITY_LOGGER_NAME]
    assert records, "no security event was emitted"
    payload = json.loads(records[-1].getMessage())
    assert payload["event_type"] == "authentication_failed"
    assert payload["request_id"] == "req-123"
    assert payload["details"]["password"] == events.REDACTED
    assert "hunter2" not in records[-1].getMessage()


def test_security_event_file_sink(tmp_path, monkeypatch):
    target = tmp_path / "security.log"
    monkeypatch.setenv("SECURITY_EVENT_LOG_FILE", str(target))
    events.log_security_event("test_event", severity="info", details={"token": "secret"})
    lines = target.read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 1
    payload = json.loads(lines[0])
    assert payload["details"]["token"] == events.REDACTED
    assert "secret" not in lines[0].replace('"secret"', "")


def test_request_correlation_id_is_generated_and_cleared():
    from app.security.context import clear_request_id, get_request_id, new_request_id, set_request_id

    assert get_request_id() == ""
    token = set_request_id("abc123")
    assert get_request_id() == "abc123"
    clear_request_id(token)
    assert get_request_id() == ""
    assert len(new_request_id()) == 32


# ---------------------------------------------------------------------------
# 3. Detection thresholds
# ---------------------------------------------------------------------------

def test_detection_thresholds_are_configurable(monkeypatch):
    monkeypatch.setenv("SEC_FAILED_LOGIN_THRESHOLD", "3")
    thresholds = DetectionThresholds.from_env()
    assert thresholds.failed_login_threshold == 3
    # Unset values fall back to the safe defaults.
    monkeypatch.delenv("SEC_ACCESS_DENIED_THRESHOLD", raising=False)
    assert DetectionThresholds.from_env().access_denied_threshold == 10


def test_single_failed_login_does_not_raise_an_event(caplog):
    detector = SecurityDetector(DetectionThresholds(failed_login_threshold=3))
    with caplog.at_level("INFO", logger=events.SECURITY_LOGGER_NAME):
        detector.record_failed_login(user_id="u1", ip_address="203.0.113.9")
    assert not [r for r in caplog.records if r.name == events.SECURITY_LOGGER_NAME]


def test_repeated_failed_logins_raise_an_event(caplog):
    detector = SecurityDetector(DetectionThresholds(failed_login_threshold=3))
    with caplog.at_level("INFO", logger=events.SECURITY_LOGGER_NAME):
        for _ in range(3):
            detector.record_failed_login(user_id="u1", ip_address="203.0.113.9")
    payloads = [
        json.loads(r.getMessage())
        for r in caplog.records
        if r.name == events.SECURITY_LOGGER_NAME
    ]
    assert any(p["event_type"] == "repeated_failed_logins" for p in payloads)
    assert any(p["event_type"] == "authentication_failed" for p in payloads) is False


def test_refresh_token_reuse_is_reported(caplog):
    detector = SecurityDetector(DetectionThresholds(refresh_reuse_threshold=1))
    with caplog.at_level("INFO", logger=events.SECURITY_LOGGER_NAME):
        detector.record_refresh_token_reuse(user_id="u1", session_family="fam-1")
    payloads = [
        json.loads(r.getMessage())
        for r in caplog.records
        if r.name == events.SECURITY_LOGGER_NAME
    ]
    assert any(p["event_type"] == "refresh_token_reuse" for p in payloads)


def test_repeated_access_denied_is_reported(caplog):
    detector = SecurityDetector(DetectionThresholds(access_denied_threshold=2))
    with caplog.at_level("INFO", logger=events.SECURITY_LOGGER_NAME):
        detector.record_access_denied(actor_id="u1", path="/api/v1/sessions")
        detector.record_access_denied(actor_id="u1", path="/api/v1/sessions")
    payloads = [
        json.loads(r.getMessage())
        for r in caplog.records
        if r.name == events.SECURITY_LOGGER_NAME
    ]
    assert any(p["event_type"] == "repeated_access_denied" for p in payloads)


def test_student_enumeration_is_reported(caplog):
    detector = SecurityDetector(DetectionThresholds(student_enumeration_threshold=3))
    with caplog.at_level("INFO", logger=events.SECURITY_LOGGER_NAME):
        for i in range(3):
            detector.record_student_lookup(actor_id="u1", usn=f"1MS21CS00{i}")
    payloads = [
        json.loads(r.getMessage())
        for r in caplog.records
        if r.name == events.SECURITY_LOGGER_NAME
    ]
    assert any(p["event_type"] == "student_data_enumeration" for p in payloads)


def test_abnormal_file_upload_is_reported(caplog):
    detector = SecurityDetector(DetectionThresholds(file_upload_threshold=2))
    with caplog.at_level("INFO", logger=events.SECURITY_LOGGER_NAME):
        detector.record_file_upload(actor_id="u1", size_bytes=1024)
        detector.record_file_upload(actor_id="u1", size_bytes=1024)
    payloads = [
        json.loads(r.getMessage())
        for r in caplog.records
        if r.name == events.SECURITY_LOGGER_NAME
    ]
    assert any(p["event_type"] == "abnormal_file_upload_activity" for p in payloads)


def test_audit_verification_failure_is_reported(caplog):
    detector = SecurityDetector()
    with caplog.at_level("INFO", logger=events.SECURITY_LOGGER_NAME):
        detector.record_audit_verification_failure(details={"modified_records": [3]})
    payloads = [
        json.loads(r.getMessage())
        for r in caplog.records
        if r.name == events.SECURITY_LOGGER_NAME
    ]
    assert any(p["event_type"] == "audit_chain_verification_failed" for p in payloads)


# ---------------------------------------------------------------------------
# 4. Decoys
# ---------------------------------------------------------------------------

def test_decoys_are_disabled_by_default(monkeypatch, db_env):
    from app.security import decoys

    monkeypatch.delenv("SECURITY_DECOY_MODE", raising=False)
    assert decoys.decoy_mode() == "off"
    assert decoys.decoys_enabled() is False
    with db_env() as db:
        decoys.create_decoy(db, decoy_kind="STUDENT", decoy_value="1DECOY001", created_by="admin_root")
        db.commit()
        assert decoys.probe_decoy(db, "1DECOY001") is False


def test_decoy_probe_raises_a_security_event(monkeypatch, db_env, caplog):
    from app.security import decoys

    monkeypatch.setenv("SECURITY_DECOY_MODE", "log")
    with db_env() as db:
        decoys.create_decoy(db, decoy_kind="STUDENT", decoy_value="1DECOY001", created_by="admin_root")
        db.commit()
        with caplog.at_level("INFO", logger=events.SECURITY_LOGGER_NAME):
            hit = decoys.probe_decoy(db, "1DECOY001", actor_id="u1")
    assert hit is True
    payloads = [
        json.loads(r.getMessage())
        for r in caplog.records
        if r.name == events.SECURITY_LOGGER_NAME
    ]
    assert any(p["event_type"] == "decoy_accessed" for p in payloads)


def test_decoys_never_enter_the_real_master_tables(monkeypatch, db_env):
    from app.security import decoys

    monkeypatch.setenv("SECURITY_DECOY_MODE", "log")
    with db_env() as db:
        decoys.create_decoy(db, decoy_kind="STUDENT", decoy_value="1DECOY001", created_by="admin_root")
        db.commit()
        students = db.execute(text("SELECT COUNT(*) FROM students")).scalar()
        attendance = db.execute(text("SELECT COUNT(*) FROM attendance")).scalar()
        sessions = db.execute(text("SELECT COUNT(*) FROM sessions")).scalar()
        decoy_rows = db.execute(text("SELECT COUNT(*) FROM security_decoys")).scalar()
    assert students == 0
    assert attendance == 0
    assert sessions == 0
    assert decoy_rows == 1


def test_decoys_are_not_reachable_through_the_ai_query_tools():
    """The AI tools must never surface decoy records."""
    from tools.query_tool import ALLOWED_TABLES

    assert "security_decoys" not in ALLOWED_TABLES


# ---------------------------------------------------------------------------
# 5. Standalone verification command
# ---------------------------------------------------------------------------

def test_verification_command_detects_tampering(chain_env, tmp_path):
    """A database without chained records is reported as unverified, never as verified."""
    db_path = tmp_path / "audit.db"
    conn = sqlite3.connect(str(db_path))
    conn.executescript(
        """
        CREATE TABLE users (user_id TEXT PRIMARY KEY, email TEXT, role TEXT,
            hashed_password TEXT, is_active INTEGER, created_at TEXT);
        CREATE TABLE audit_log (log_id INTEGER PRIMARY KEY AUTOINCREMENT, actor_id TEXT,
            actor_role TEXT, action TEXT, session_id TEXT, usn TEXT, entity_type TEXT,
            entity_id TEXT, old_value TEXT, new_value TEXT, reason TEXT, timestamp TEXT);
        """
    )
    conn.execute(
        "INSERT INTO users VALUES ('admin_root','a@b.c','ADMIN',NULL,1,'2026-01-01T00:00:00Z')"
    )
    conn.execute(
        "INSERT INTO audit_log (actor_id, actor_role, action, session_id, usn, entity_type, "
        "entity_id, old_value, new_value, reason, timestamp) VALUES "
        "('admin_root','ADMIN','LEGACY_ACTION','SESS-1','1MS21CS001','attendance','ATT-1',"
        "NULL,NULL,NULL,'2020-01-01T00:00:00Z')"
    )
    conn.commit()
    conn.close()

    env = dict(os.environ)
    env["AUDIT_CHAIN_HMAC_SECRET"] = CHAIN_SECRET
    env["PYTHONPATH"] = str(BACKEND_DIR)

    result = subprocess.run(
        [sys.executable, "-m", "tools.verify_audit_chain", "--db", str(db_path)],
        cwd=str(BACKEND_DIR),
        env=env,
        capture_output=True,
        text=True,
        timeout=120,
    )
    output = result.stdout + result.stderr
    assert result.returncode == 0, output
    # The legacy record must be reported as unverified, not as verified.
    assert "legacy" in output.lower()
    assert "verified records       : 0" in output


def test_verification_command_on_a_chained_database(chain_env, tmp_path):
    db_path = tmp_path / "chained.db"
    conn = sqlite3.connect(str(db_path))
    conn.executescript(
        """
        CREATE TABLE users (user_id TEXT PRIMARY KEY, email TEXT, role TEXT,
            hashed_password TEXT, is_active INTEGER, created_at TEXT);
        CREATE TABLE audit_log (log_id INTEGER PRIMARY KEY AUTOINCREMENT, actor_id TEXT,
            actor_role TEXT, action TEXT, session_id TEXT, usn TEXT, entity_type TEXT,
            entity_id TEXT, old_value TEXT, new_value TEXT, reason TEXT, timestamp TEXT,
            chain_id TEXT, prev_hash TEXT, row_hash TEXT);
        CREATE TABLE audit_chain_head (chain_id TEXT PRIMARY KEY, last_hash TEXT,
            last_log_id INTEGER, updated_at TEXT);
        """
    )
    conn.execute(
        "INSERT INTO users VALUES ('admin_root','a@b.c','ADMIN',NULL,1,'2026-01-01T00:00:00Z')"
    )
    conn.commit()
    conn.close()

    engine = create_engine(f"sqlite:///{db_path.as_posix()}")
    factory = sessionmaker(bind=engine, class_=OrmSession, expire_on_commit=False)
    with factory() as db:
        for i in range(3):
            crud.create_audit_entry(
                db,
                actor_id="admin_root",
                actor_role="ADMIN",
                action="ATTENDANCE_UPSERT",
                entity_type="attendance",
                entity_id=f"ATT-{i}",
                old_value="PRESENT",
                new_value="ABSENT",
            )
        db.commit()
    engine.dispose()

    env = dict(os.environ)
    env["AUDIT_CHAIN_HMAC_SECRET"] = CHAIN_SECRET
    env["PYTHONPATH"] = str(BACKEND_DIR)
    result = subprocess.run(
        [sys.executable, "-m", "tools.verify_audit_chain", "--db", str(db_path)],
        cwd=str(BACKEND_DIR),
        env=env,
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "INTACT" in result.stdout

    # Tamper with the stored content and verify the command detects it.
    conn = sqlite3.connect(str(db_path))
    conn.execute("UPDATE audit_log SET new_value = 'TAMPERED' WHERE log_id = 1")
    conn.commit()
    conn.close()
    result = subprocess.run(
        [sys.executable, "-m", "tools.verify_audit_chain", "--db", str(db_path)],
        cwd=str(BACKEND_DIR),
        env=env,
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert result.returncode == 1, result.stdout + result.stderr
    assert "TAMPERING DETECTED" in result.stdout


# ---------------------------------------------------------------------------
# 6. CI configuration
# ---------------------------------------------------------------------------

def test_ci_workflow_contains_the_required_checks():
    workflow = (REPO_ROOT / ".github" / "workflows" / "security.yml").read_text(encoding="utf-8")
    for required in (
        "gitleaks",
        "pip-audit",
        "pip_audit",
        "bandit",
        "npm audit",
        "pytest",
        "tsc -b",
        "npm run lint",
        "alembic",
    ):
        assert required.lower() in workflow.lower(), f"CI workflow is missing: {required}"


def test_ci_workflow_pins_tool_versions():
    workflow = (REPO_ROOT / ".github" / "workflows" / "security.yml").read_text(encoding="utf-8")
    assert re.search(r"PIP_AUDIT_VERSION:\s*\"[0-9][^\"]*\"", workflow)
    assert re.search(r"BANDIT_VERSION:\s*\"[0-9][^\"]*\"", workflow)
    assert re.search(r"GITLEAKS_VERSION:\s*\"[0-9][^\"]*\"", workflow)


def test_migration_for_the_hash_chain_is_present_and_not_applied():
    migration = BACKEND_DIR / "alembic" / "versions" / "0015_audit_hash_chain.py"
    assert migration.exists()
    source = migration.read_text(encoding="utf-8")
    assert "prev_hash" in source and "row_hash" in source
    assert "audit_chain_head" in source
    # The HMAC secret must never be provisioned by the migration.
    assert "os.environ" not in source
    assert "getenv" not in source
