"""Query tool for safe, read-only database inspections and analytics.

Enforces read-only operations, parameterized queries, and strict validation
against SQL injection, multi-statement executions, schema mutations, and
unauthorized table access across both Supabase and SQLite backends.
"""

from __future__ import annotations

import os
import re
import sqlite3
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Union

from app.db.connection import (
    DEFAULT_DB_PATH,
    READONLY_DATABASE_URL,
    DATABASE_URL,
    get_backend,
    get_connection,
)

NO_DATA_MESSAGE = "I do not have that data."

ALLOWED_TABLES = {"students", "rooms", "sessions", "attendance"}

# Regex pattern disallowing statements that modify data or schema
DISALLOWED_SQL_KEYWORDS = re.compile(
    r"\b(INSERT|UPDATE|DELETE|DROP|ALTER|CREATE|ATTACH|DETACH|REPLACE|TRUNCATE|PRAGMA|VACUUM|REINDEX|GRANT|REVOKE)\b",
    re.IGNORECASE,
)


@dataclass
class QueryResult:
    """Structured result for database query operations."""

    found: bool
    data: List[Dict[str, Any]]
    total_count: int
    message: str
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


class _ReadOnlyDB:
    """Unified read-only connection wrapper for SQLite or Supabase (SQLAlchemy)."""

    def __init__(self, mode: str, conn: Any, should_close: bool = True):
        self.mode = mode
        self.conn = conn
        self.should_close = should_close

    def execute(self, sql: str, params: Union[Tuple[Any, ...], List[Any], Dict[str, Any]] = ()):
        if self.mode == "sqlalchemy":
            from sqlalchemy import text
            if isinstance(params, (list, tuple)):
                # Convert ? to positional or named if needed, or pass tuple
                # In SQLAlchemy text(), :p0, :p1 can be used or sqlite positional
                p_dict = {f"p{i}": v for i, v in enumerate(params)}
                named_sql = sql
                for i in range(len(params)):
                    named_sql = re.sub(r"\?", f":p{i}", named_sql, count=1)
                return self.conn.execute(text(named_sql), p_dict)
            else:
                return self.conn.execute(text(sql), params)
        else:
            cursor = self.conn.cursor()
            cursor.execute(sql, tuple(params) if isinstance(params, (list, tuple)) else params)
            return cursor

    def close(self):
        if self.should_close:
            self.conn.close()


def _get_readonly_conn(
    db_target: Union[str, sqlite3.Connection, Any] = DEFAULT_DB_PATH
) -> _ReadOnlyDB:
    """
    Get a read-only database connection.
    In supabase mode: uses READONLY_DATABASE_URL (or DATABASE_URL).
    In sqlite mode: opens the file strictly in read-only URI mode (?mode=ro).
    """
    if isinstance(db_target, sqlite3.Connection):
        return _ReadOnlyDB("sqlite", db_target, should_close=False)

    # Check backend first if default or supabase target
    backend = get_backend()
    if backend == "supabase" and (db_target == DEFAULT_DB_PATH or db_target == "default"):
        ro_url = os.getenv("READONLY_DATABASE_URL") or os.getenv("DATABASE_URL", DATABASE_URL)
        if not ro_url:
            raise ConnectionError("Database connection failed: READONLY_DATABASE_URL or DATABASE_URL not configured.")
        try:
            from sqlalchemy import create_engine
            if ro_url.startswith("postgres://"):
                ro_url = ro_url.replace("postgres://", "postgresql://", 1)
            engine = create_engine(ro_url, pool_pre_ping=True)
            conn = engine.connect()
            return _ReadOnlyDB("sqlalchemy", conn, should_close=True)
        except Exception as exc:
            raise ConnectionError(f"Database connection failed: {exc}")

    # Check if a custom non-default sqlite path or :memory: was passed
    if isinstance(db_target, str) and db_target != DEFAULT_DB_PATH and db_target != "default":
        if db_target == ":memory:":
            conn = get_connection(db_target)
            return _ReadOnlyDB("sqlite", conn, should_close=True)
        resolved = Path(db_target).resolve()
        if not resolved.exists():
            raise FileNotFoundError(f"Database file not found: {db_target}")
        uri_path = f"file:{resolved.as_posix()}?mode=ro"
        try:
            conn = sqlite3.connect(uri_path, uri=True)
        except sqlite3.OperationalError:
            conn = sqlite3.connect(str(resolved))
        conn.row_factory = sqlite3.Row
        return _ReadOnlyDB("sqlite", conn, should_close=True)

    # SQLite default path
    resolved_path = Path(DEFAULT_DB_PATH).resolve()
    if not resolved_path.exists():
        raise FileNotFoundError(f"Database file not found: {DEFAULT_DB_PATH}")

    uri_path = f"file:{resolved_path.as_posix()}?mode=ro"
    try:
        conn = sqlite3.connect(uri_path, uri=True)
    except sqlite3.OperationalError:
        conn = sqlite3.connect(str(resolved_path))
    conn.row_factory = sqlite3.Row
    return _ReadOnlyDB("sqlite", conn, should_close=True)


def _rows_to_dicts(rows: Any) -> List[Dict[str, Any]]:
    results = []
    for r in rows:
        if isinstance(r, dict):
            results.append(r)
        elif hasattr(r, "_mapping"):
            results.append(dict(r._mapping))
        else:
            results.append(dict(r))
    return results


def validate_read_only_sql(sql: str) -> None:
    """
    Validate that an SQL string is strictly a single, read-only SELECT statement
    querying only allowed tables (students, rooms, sessions, attendance).
    """
    if not sql or not isinstance(sql, str):
        raise ValueError("Query must be a non-empty string.")

    # Remove comments and strip whitespace
    cleaned = re.sub(r"--.*$", "", sql, flags=re.MULTILINE)
    cleaned = re.sub(r"/\*.*?\*/", "", cleaned, flags=re.DOTALL).strip()

    if not cleaned:
        raise ValueError("Query cannot be empty after stripping comments.")

    # Disallow multiple statements (semicolon separating statements)
    statements = [s.strip() for s in cleaned.split(";") if s.strip()]
    if len(statements) > 1:
        raise ValueError("Multiple SQL statements are not permitted.")

    # Must start with SELECT only (one SELECT statement)
    single_stmt = statements[0]
    if not re.match(r"^SELECT\b", single_stmt, re.IGNORECASE):
        raise ValueError("Only a single SELECT query is allowed.")

    # Disallow mutation or administrative keywords
    if DISALLOWED_SQL_KEYWORDS.search(single_stmt):
        match = DISALLOWED_SQL_KEYWORDS.search(single_stmt)
        disallowed = match.group(0) if match else "MUTATION"
        raise ValueError(f"Disallowed keyword detected in query: {disallowed}")

    # Extract referenced table names from FROM / JOIN clauses
    table_pattern = re.compile(r"\b(?:FROM|JOIN)\s+([a-zA-Z_][a-zA-Z0-9_]*)", re.IGNORECASE)
    tables_found = set(table_pattern.findall(single_stmt))
    if not tables_found:
        raise ValueError("Query must reference at least one valid table.")

    for tbl in tables_found:
        if tbl.lower() not in ALLOWED_TABLES:
            raise ValueError(f"Access to table '{tbl}' is not permitted. Allowed tables: {sorted(ALLOWED_TABLES)}")


def safe_sql_query(
    sql: str,
    params: Union[Tuple[Any, ...], List[Any]] = (),
    db_target: Union[str, sqlite3.Connection, Any] = DEFAULT_DB_PATH,
    limit: int = 500,
) -> QueryResult:
    """
    Execute an arbitrary read-only SQL query with parameterized values and validation.
    """
    validate_read_only_sql(sql)

    ro_db = _get_readonly_conn(db_target)
    try:
        res = ro_db.execute(sql, params)
        if ro_db.mode == "sqlalchemy":
            rows = res.fetchmany(max(1, limit))
        else:
            rows = res.fetchmany(max(1, limit))
        results = _rows_to_dicts(rows)
        found = len(results) > 0
        message = f"Found {len(results)} records." if found else NO_DATA_MESSAGE
        return QueryResult(
            found=found,
            data=results,
            total_count=len(results),
            message=message,
            metadata={"query": sql, "limit": limit},
        )
    except Exception as exc:
        return QueryResult(
            found=False,
            data=[],
            total_count=0,
            message=f"Query error: {exc}",
            metadata={"query": sql, "error": str(exc)},
        )
    finally:
        ro_db.close()


def query_attendance(
    session_id: Optional[str] = None,
    room_id: Optional[str] = None,
    branch: Optional[str] = None,
    usn: Optional[str] = None,
    status: Optional[str] = None,
    limit: int = 500,
    db_target: Union[str, sqlite3.Connection, Any] = DEFAULT_DB_PATH,
) -> QueryResult:
    """
    Query attendance records with optional filtering by session, room, branch, USN, and status.
    Returns structured results joining student and room metadata.
    """
    ro_db = _get_readonly_conn(db_target)
    try:
        clauses = []
        params: List[Any] = []

        if session_id:
            clauses.append("a.session_id = ?")
            params.append(str(session_id).strip())
        if room_id:
            clauses.append("a.room_id = ?")
            params.append(str(room_id).strip())
        if branch:
            clauses.append("LOWER(stu.branch) = LOWER(?)")
            params.append(str(branch).strip())
        if usn:
            clauses.append("UPPER(a.usn) = UPPER(?)")
            params.append(str(usn).strip())
        if status:
            clauses.append("UPPER(a.status) = UPPER(?)")
            params.append(str(status).strip())

        where_sql = ("WHERE " + " AND ".join(clauses)) if clauses else ""

        sql = f"""
        SELECT
            a.session_id,
            sess.date AS session_date,
            sess.subject,
            a.usn,
            stu.name AS student_name,
            stu.branch,
            a.room_id,
            rm.name AS room_name,
            a.status,
            a.source,
            a.confidence
        FROM attendance a
        LEFT JOIN sessions sess ON a.session_id = sess.session_id
        LEFT JOIN students stu ON a.usn = stu.usn
        LEFT JOIN rooms rm ON a.room_id = rm.room_id
        {where_sql}
        ORDER BY a.session_id ASC, a.room_id ASC, stu.name ASC
        """
        res = ro_db.execute(sql, tuple(params))
        if ro_db.mode == "sqlalchemy":
            records = _rows_to_dicts(res.fetchmany(max(1, limit)))
        else:
            records = _rows_to_dicts(res.fetchmany(max(1, limit)))
        found = len(records) > 0

        return QueryResult(
            found=found,
            data=records,
            total_count=len(records),
            message=f"Found {len(records)} attendance records." if found else NO_DATA_MESSAGE,
            metadata={
                "session_id": session_id,
                "room_id": room_id,
                "branch": branch,
                "usn": usn,
                "status": status,
            },
        )
    except Exception as exc:
        return QueryResult(
            found=False,
            data=[],
            total_count=0,
            message=f"Error querying attendance: {exc}",
            metadata={"error": str(exc)},
        )
    finally:
        ro_db.close()


def query_students(
    usn: Optional[str] = None,
    branch: Optional[str] = None,
    name: Optional[str] = None,
    limit: int = 500,
    db_target: Union[str, sqlite3.Connection, Any] = DEFAULT_DB_PATH,
) -> QueryResult:
    """Query student directory with optional filters."""
    ro_db = _get_readonly_conn(db_target)
    try:
        clauses = []
        params: List[Any] = []

        if usn:
            clauses.append("UPPER(usn) = UPPER(?)")
            params.append(str(usn).strip())
        if branch:
            clauses.append("LOWER(branch) = LOWER(?)")
            params.append(str(branch).strip())
        if name:
            clauses.append("LOWER(name) LIKE LOWER(?)")
            params.append(f"%{str(name).strip()}%")

        where_sql = ("WHERE " + " AND ".join(clauses)) if clauses else ""
        sql = f"SELECT usn, name, branch FROM students {where_sql} ORDER BY usn ASC"

        res = ro_db.execute(sql, tuple(params))
        records = _rows_to_dicts(res.fetchmany(max(1, limit)))
        found = len(records) > 0

        return QueryResult(
            found=found,
            data=records,
            total_count=len(records),
            message=f"Found {len(records)} students." if found else NO_DATA_MESSAGE,
            metadata={"usn": usn, "branch": branch, "name": name},
        )
    except Exception as exc:
        return QueryResult(
            found=False,
            data=[],
            total_count=0,
            message=f"Error querying students: {exc}",
            metadata={"error": str(exc)},
        )
    finally:
        ro_db.close()


def query_session_stats(
    session_id: str,
    db_target: Union[str, sqlite3.Connection, Any] = DEFAULT_DB_PATH,
) -> QueryResult:
    """Calculate attendance statistics for a given session."""
    clean_id = str(session_id).strip()
    if not clean_id:
        return QueryResult(
            found=False,
            data=[],
            total_count=0,
            message="session_id cannot be empty.",
            metadata={},
        )

    ro_db = _get_readonly_conn(db_target)
    try:
        sql_session = "SELECT session_id, date, subject FROM sessions WHERE session_id = ?"
        res = ro_db.execute(sql_session, (clean_id,))
        row = res.fetchone()
        if not row:
            return QueryResult(
                found=False,
                data=[],
                total_count=0,
                message=NO_DATA_MESSAGE,
                metadata={"session_id": clean_id, "reason": "Session does not exist"},
            )

        sess_dict = dict(row._mapping) if hasattr(row, "_mapping") else dict(row)

        sql_stats = """
        SELECT
            status,
            COUNT(*) AS count
        FROM attendance
        WHERE session_id = ?
        GROUP BY status
        """
        res_stats = ro_db.execute(sql_stats, (clean_id,))
        status_rows = res_stats.fetchall()
        status_counts: Dict[str, int] = {
            "PRESENT": 0,
            "ABSENT": 0,
            "PENDING": 0,
            "UNREVIEWED": 0,
        }
        total = 0
        for r in status_rows:
            mapping = dict(r._mapping) if hasattr(r, "_mapping") else dict(r)
            st = str(mapping["status"]).upper()
            cnt = int(mapping["count"])
            status_counts[st] = status_counts.get(st, 0) + cnt
            total += cnt

        if total == 0:
            return QueryResult(
                found=False,
                data=[],
                total_count=0,
                message=NO_DATA_MESSAGE,
                metadata={"session_id": clean_id, "reason": "No attendance records found"},
            )

        present = status_counts.get("PRESENT", 0)
        absent = status_counts.get("ABSENT", 0)
        pending = status_counts.get("PENDING", 0)
        unreviewed = status_counts.get("UNREVIEWED", 0)
        confirmed = present + absent
        confirmed_percentage = round((present / confirmed) * 100, 2) if confirmed > 0 else 0.0
        attendance_percentage = round((present / total) * 100, 2) if total > 0 else 0.0

        stats_payload = {
            "session_id": clean_id,
            "date": sess_dict.get("date"),
            "subject": sess_dict.get("subject"),
            "total": total,
            "total_students": total,
            "present": present,
            "present_count": present,
            "absent": absent,
            "absent_count": absent,
            "pending": pending,
            "pending_count": pending,
            "unreviewed": unreviewed,
            "unreviewed_count": unreviewed,
            "confirmed": confirmed,
            "confirmed_percentage": confirmed_percentage,
            "attendance_percentage": attendance_percentage,
        }

        return QueryResult(
            found=True,
            data=[stats_payload],
            total_count=1,
            message=f"Statistics calculated for session '{clean_id}'. Attendance rate: {attendance_percentage}%.",
            metadata=stats_payload,
        )
    except Exception as exc:
        return QueryResult(
            found=False,
            data=[],
            total_count=0,
            message=f"Error calculating session stats: {exc}",
            metadata={"error": str(exc)},
        )
    finally:
        ro_db.close()


def query_absentees(
    session_id: Optional[str] = None,
    room_id: Optional[str] = None,
    branch: Optional[str] = None,
    limit: int = 500,
    db_target: Union[str, sqlite3.Connection, Any] = DEFAULT_DB_PATH,
) -> QueryResult:
    """Retrieve absent students for a given session or room/branch combination."""
    return query_attendance(
        session_id=session_id,
        room_id=room_id,
        branch=branch,
        status="ABSENT",
        limit=limit,
        db_target=db_target,
    )


def query_tool(
    query_type: str = "attendance",
    session_id: Optional[str] = None,
    room_id: Optional[str] = None,
    branch: Optional[str] = None,
    usn: Optional[str] = None,
    status: Optional[str] = None,
    sql: Optional[str] = None,
    params: Optional[Union[Tuple[Any, ...], List[Any]]] = None,
    limit: int = 500,
    db_target: Union[str, sqlite3.Connection, Any] = DEFAULT_DB_PATH,
    **kwargs: Any,
) -> QueryResult:
    """Universal dispatcher for database query operations."""
    clean_type = str(query_type).strip().lower()

    if clean_type in ("attendance", "records"):
        return query_attendance(
            session_id=session_id,
            room_id=room_id,
            branch=branch,
            usn=usn,
            status=status,
            limit=limit,
            db_target=db_target,
        )
    if clean_type in ("session_stats", "stats", "session"):
        if not session_id:
            return QueryResult(
                found=False,
                data=[],
                total_count=0,
                message="session_id is required for session_stats query.",
                metadata={},
            )
        return query_session_stats(session_id=session_id, db_target=db_target)
    if clean_type in ("absentees", "absent"):
        return query_absentees(
            session_id=session_id,
            room_id=room_id,
            branch=branch,
            limit=limit,
            db_target=db_target,
        )
    if clean_type in ("students", "student"):
        return query_students(
            usn=usn,
            branch=branch,
            name=kwargs.get("name"),
            limit=limit,
            db_target=db_target,
        )
    if clean_type in ("sql", "custom_sql"):
        if not sql:
            return QueryResult(
                found=False,
                data=[],
                total_count=0,
                message="sql parameter is required for custom_sql query.",
                metadata={},
            )
        return safe_sql_query(
            sql=sql,
            params=params or (),
            db_target=db_target,
            limit=limit,
        )

    return QueryResult(
        found=False,
        data=[],
        total_count=0,
        message=f"Unsupported query_type '{query_type}'. Allowed: attendance, session_stats, absentees, students, sql.",
        metadata={"query_type": query_type},
    )
