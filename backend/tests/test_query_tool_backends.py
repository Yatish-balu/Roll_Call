"""Tests for query_tool and safe queries across both SQLite and Supabase Postgres backends."""

import os
import csv
import sqlite3
import pytest
from pathlib import Path
from app.db.schema import init_db
from app.db.crud import insert_student, insert_room, insert_session, insert_attendance
from tools.query_tool import (
    safe_sql_query,
    validate_read_only_sql,
    _get_readonly_conn,
)


@pytest.fixture(params=["sqlite", "supabase"])
def backend_setup(request, tmp_path):
    """
    Parametrized fixture providing database setup for both backends:
    - 'sqlite': creates a temporary SQLite database initialized with schema and seed data.
    - 'supabase': connects using READONLY_DATABASE_URL / DATABASE_URL if available; skips if unconfigured.
    """
    backend = request.param
    test1_csv = Path(__file__).resolve().parents[2] / "data" / "test1.csv"
    if not test1_csv.exists():
        test1_csv = Path(__file__).resolve().parents[1] / "data" / "test1.csv"

    # Read data/test1.csv
    records = []
    with open(test1_csv, mode="r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            records.append(row)

    if backend == "sqlite":
        db_path = str(tmp_path / "test_attendance.db")
        conn = sqlite3.connect(db_path)
        init_db(conn)

        # Seed data matching test1.csv
        insert_session(conn, session_id="SESS-TEST1", date="2026-11-08", subject="System Testing")
        for r in records:
            try:
                insert_student(conn, usn=r["usn"], name=r["name"], branch=r["branch"])
            except Exception:
                pass
            try:
                insert_room(conn, room_id=r["room_id"], name=f"Room {r['room_id']}")
            except Exception:
                pass
            insert_attendance(
                conn,
                session_id="SESS-TEST1",
                usn=r["usn"],
                room_id=r["room_id"],
                status=r["status"],
                source="test1_csv",
            )
        conn.close()

        old_backend = os.environ.get("DB_BACKEND")
        old_sqlite = os.environ.get("SQLITE_PATH")
        os.environ["DB_BACKEND"] = "sqlite"
        os.environ["SQLITE_PATH"] = db_path

        yield {"backend": "sqlite", "target": db_path, "expected_count": len(records)}

        if old_backend is not None:
            os.environ["DB_BACKEND"] = old_backend
        else:
            os.environ.pop("DB_BACKEND", None)

        if old_sqlite is not None:
            os.environ["SQLITE_PATH"] = old_sqlite
        else:
            os.environ.pop("SQLITE_PATH", None)

    elif backend == "supabase":
        ro_url = os.environ.get("READONLY_DATABASE_URL") or os.environ.get("DATABASE_URL")
        if not ro_url:
            pytest.skip("Supabase READONLY_DATABASE_URL or DATABASE_URL not configured")

        old_backend = os.environ.get("DB_BACKEND")
        os.environ["DB_BACKEND"] = "supabase"

        yield {"backend": "supabase", "target": None, "expected_count": len(records)}

        if old_backend is not None:
            os.environ["DB_BACKEND"] = old_backend
        else:
            os.environ.pop("DB_BACKEND", None)


def test_counts_match_test1_csv(backend_setup):
    """Verify that student and attendance counts match data/test1.csv."""
    target = backend_setup["target"]
    expected = backend_setup["expected_count"]

    if backend_setup["backend"] == "sqlite":
        res = safe_sql_query("SELECT COUNT(*) AS total FROM attendance WHERE session_id = 'SESS-TEST1'", db_target=target)
        assert res.found is True
        total = list(res.data[0].values())[0]
        assert total == expected
    else:
        # In supabase mode verify query execution
        res = safe_sql_query("SELECT COUNT(*) AS total FROM attendance")
        assert res.found is True


def test_db_down_gives_clear_error(monkeypatch):
    """Verify that when the database is unreachable or down, a clear error is produced."""
    # Test SQLite missing database file
    with pytest.raises((FileNotFoundError, ConnectionError)) as exc_info:
        _get_readonly_conn(db_target="non_existent_dir/missing_db.db")
    assert "Database file not found" in str(exc_info.value)

    # Test Supabase down / invalid URL
    monkeypatch.setenv("DB_BACKEND", "supabase")
    monkeypatch.setenv("READONLY_DATABASE_URL", "postgresql://invalid_user:invalid_pwd@localhost:5433/invalid_db")
    with pytest.raises(ConnectionError) as exc_info_sb:
        _get_readonly_conn(db_target="default")
    assert "Database connection failed" in str(exc_info_sb.value)


def test_drop_and_multi_statement_blocked(backend_setup):
    """Verify that DROP and multi-statement queries are strictly blocked before execution."""
    target = backend_setup["target"]

    # 1. DROP statement blocked
    with pytest.raises(ValueError) as exc_drop:
        safe_sql_query("DROP TABLE students", db_target=target if target else "default")
    assert "Only a single SELECT query is allowed" in str(exc_drop.value) or "Disallowed keyword" in str(exc_drop.value)

    # 2. DROP with SELECT blocked
    with pytest.raises(ValueError) as exc_drop_inline:
        safe_sql_query("SELECT * FROM students; DROP TABLE students;", db_target=target if target else "default")
    assert "Multiple SQL statements are not permitted" in str(exc_drop_inline.value)

    # 3. Multi-statement blocked
    with pytest.raises(ValueError) as exc_multi:
        safe_sql_query("SELECT * FROM students; SELECT * FROM rooms;", db_target=target if target else "default")
    assert "Multiple SQL statements are not permitted" in str(exc_multi.value)

    # 4. Unauthorized tables blocked
    with pytest.raises(ValueError) as exc_unauth:
        safe_sql_query("SELECT * FROM secret_credentials", db_target=target if target else "default")
    assert "Access to table 'secret_credentials' is not permitted" in str(exc_unauth.value)

