"""Query tool for safe, read-only database inspections and analytics.

Enforces read-only operations, parameterized queries, and strict validation
against SQL injection, multi-statement executions, schema mutations, and
unauthorized table access.
"""

from __future__ import annotations

import os
import re
import sqlite3
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Union

from app.db.connection import DEFAULT_DB_PATH, get_connection

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


def _get_readonly_conn(
    db_target: Union[str, sqlite3.Connection] = DEFAULT_DB_PATH
) -> Tuple[sqlite3.Connection, bool]:
    """
    Get a database connection. If a file path is provided, opens in read-only URI mode.
    Returns (connection, should_close).
    """
    if isinstance(db_target, sqlite3.Connection):
        return db_target, False

    db_path = str(db_target)
    if db_path == ":memory:":
        conn = get_connection(db_path)
        return conn, True

    resolved_path = Path(db_path).resolve()
    if not resolved_path.exists():
        raise FileNotFoundError(f"Database file not found: {db_path}")

    # Use URI mode=ro for strict OS/SQLite-level read-only protection
    uri_path = f"file:{resolved_path.as_posix()}?mode=ro"
    try:
        conn = sqlite3.connect(uri_path, uri=True)
    except sqlite3.OperationalError:
        # Fallback to standard connect if URI fails
        conn = sqlite3.connect(str(resolved_path))
    conn.row_factory = sqlite3.Row
    return conn, True


def _rows_to_dicts(rows: List[sqlite3.Row]) -> List[Dict[str, Any]]:
    return [dict(row) for row in rows]


def validate_read_only_sql(sql: str) -> None:
    """
    Validate that an SQL string is strictly a single, read-only SELECT statement
    querying only allowed tables.
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

    # Must start with SELECT or WITH (for CTE read queries)
    single_stmt = statements[0]
    if not re.match(r"^(SELECT|WITH)\b", single_stmt, re.IGNORECASE):
        raise ValueError("Only SELECT or WITH (read-only) queries are allowed.")

    # Disallow mutation keywords anywhere in statement
    if DISALLOWED_SQL_KEYWORDS.search(single_stmt):
        match = DISALLOWED_SQL_KEYWORDS.search(single_stmt)
        disallowed = match.group(0) if match else "MUTATION"
        raise ValueError(f"Disallowed keyword detected in query: {disallowed}")

    # Extract referenced table names from FROM / JOIN clauses
    table_pattern = re.compile(r"\b(?:FROM|JOIN)\s+([a-zA-Z_][a-zA-Z0-9_]*)", re.IGNORECASE)
    tables_found = set(table_pattern.findall(single_stmt))
    for tbl in tables_found:
        if tbl.lower() not in ALLOWED_TABLES:
            raise ValueError(f"Access to table '{tbl}' is not permitted. Allowed tables: {sorted(ALLOWED_TABLES)}")


def safe_sql_query(
    sql: str,
    params: Union[Tuple[Any, ...], List[Any]] = (),
    db_target: Union[str, sqlite3.Connection] = DEFAULT_DB_PATH,
    limit: int = 500,
) -> QueryResult:
    """
    Execute an arbitrary read-only SQL query with parameterized values and validation.
    """
    validate_read_only_sql(sql)

    conn, should_close = _get_readonly_conn(db_target)
    try:
        cursor = conn.cursor()
        cursor.execute(sql, tuple(params))
        rows = cursor.fetchmany(max(1, limit))
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
        if should_close:
            conn.close()


def query_attendance(
    session_id: Optional[str] = None,
    room_id: Optional[str] = None,
    branch: Optional[str] = None,
    usn: Optional[str] = None,
    status: Optional[str] = None,
    limit: int = 500,
    db_target: Union[str, sqlite3.Connection] = DEFAULT_DB_PATH,
) -> QueryResult:
    """
    Query attendance records with optional filtering by session, room, branch, USN, and status.
    Returns structured results joining student and room metadata.
    """
    conn, should_close = _get_readonly_conn(db_target)
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
        LIMIT ?
        """
        params.append(max(1, limit))

        cursor = conn.cursor()
        cursor.execute(sql, tuple(params))
        records = _rows_to_dicts(cursor.fetchall())
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
        if should_close:
            conn.close()


def query_students(
    usn: Optional[str] = None,
    branch: Optional[str] = None,
    name: Optional[str] = None,
    limit: int = 500,
    db_target: Union[str, sqlite3.Connection] = DEFAULT_DB_PATH,
) -> QueryResult:
    """
    Query student records with optional filters.
    """
    conn, should_close = _get_readonly_conn(db_target)
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
            clauses.append("name LIKE ?")
            params.append(f"%{str(name).strip()}%")

        where_sql = ("WHERE " + " AND ".join(clauses)) if clauses else ""
        sql = f"SELECT usn, name, branch FROM students {where_sql} ORDER BY usn ASC LIMIT ?"
        params.append(max(1, limit))

        cursor = conn.cursor()
        cursor.execute(sql, tuple(params))
        records = _rows_to_dicts(cursor.fetchall())
        found = len(records) > 0

        return QueryResult(
            found=found,
            data=records,
            total_count=len(records),
            message=f"Found {len(records)} student records." if found else NO_DATA_MESSAGE,
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
        if should_close:
            conn.close()


def query_session_stats(
    session_id: str,
    db_target: Union[str, sqlite3.Connection] = DEFAULT_DB_PATH,
) -> QueryResult:
    """
    Calculate deterministic summary statistics for a given session.
    Confirmed attendance percentage is strictly: PRESENT / (PRESENT + ABSENT) * 100.
    Handles zero denominator without division errors.
    Returns NO_DATA_MESSAGE if session or session attendance does not exist.
    """
    if not session_id or not str(session_id).strip():
        return QueryResult(
            found=False,
            data=[],
            total_count=0,
            message="session_id is required.",
            metadata={"session_id": session_id},
        )

    clean_id = str(session_id).strip()
    conn, should_close = _get_readonly_conn(db_target)
    try:
        # Check session metadata
        sess_cursor = conn.cursor()
        sess_cursor.execute(
            "SELECT session_id, date, subject FROM sessions WHERE session_id = ?",
            (clean_id,),
        )
        sess_row = sess_cursor.fetchone()
        if not sess_row:
            return QueryResult(
                found=False,
                data=[],
                total_count=0,
                message=NO_DATA_MESSAGE,
                metadata={"session_id": clean_id, "reason": "session not found"},
            )

        # Count attendance states
        att_cursor = conn.cursor()
        att_cursor.execute(
            """
            SELECT
                status,
                COUNT(*) as count
            FROM attendance
            WHERE session_id = ?
            GROUP BY status
            """,
            (clean_id,),
        )
        counts = {row["status"]: row["count"] for row in att_cursor.fetchall()}

        present = counts.get("PRESENT", 0)
        absent = counts.get("ABSENT", 0)
        pending = counts.get("PENDING", 0)
        unreviewed = counts.get("UNREVIEWED", 0)
        unresolved = pending + unreviewed
        confirmed = present + absent
        total = present + absent + pending + unreviewed

        if total == 0:
            return QueryResult(
                found=False,
                data=[],
                total_count=0,
                message=NO_DATA_MESSAGE,
                metadata={"session_id": clean_id, "reason": "no attendance recorded for session"},
            )

        confirmed_percentage = round((present / confirmed * 100), 2) if confirmed > 0 else 0.0

        stats_dict = {
            "session_id": clean_id,
            "date": sess_row["date"],
            "subject": sess_row["subject"],
            "present": present,
            "absent": absent,
            "pending": pending,
            "unreviewed": unreviewed,
            "unresolved": unresolved,
            "confirmed": confirmed,
            "total": total,
            "confirmed_percentage": confirmed_percentage,
        }

        return QueryResult(
            found=True,
            data=[stats_dict],
            total_count=1,
            message=f"Session {clean_id}: Present={present}, Absent={absent}, Total={total}, Attendance={confirmed_percentage}%.",
            metadata=stats_dict,
        )
    except Exception as exc:
        return QueryResult(
            found=False,
            data=[],
            total_count=0,
            message=f"Error computing session stats: {exc}",
            metadata={"session_id": clean_id, "error": str(exc)},
        )
    finally:
        if should_close:
            conn.close()


def query_absentees(
    session_id: Optional[str] = None,
    room_id: Optional[str] = None,
    branch: Optional[str] = None,
    limit: int = 500,
    db_target: Union[str, sqlite3.Connection] = DEFAULT_DB_PATH,
) -> QueryResult:
    """
    Query all absent students for a given session, room, or branch.
    """
    return query_attendance(
        session_id=session_id,
        room_id=room_id,
        branch=branch,
        status="ABSENT",
        limit=limit,
        db_target=db_target,
    )


def query_tool(
    query_type: str,
    *,
    session_id: Optional[str] = None,
    room_id: Optional[str] = None,
    branch: Optional[str] = None,
    usn: Optional[str] = None,
    status: Optional[str] = None,
    sql: Optional[str] = None,
    params: Optional[Union[Tuple[Any, ...], List[Any]]] = None,
    limit: int = 500,
    db_target: Union[str, sqlite3.Connection] = DEFAULT_DB_PATH,
    **kwargs: Any,
) -> QueryResult:
    """
    Unified dispatcher for read-only database query operations.

    Supported query_type values:
    - 'attendance': Query attendance records with filters.
    - 'session_stats': Calculate stats (present, absent, percentage) for session_id.
    - 'absentees': List absent students.
    - 'students': Query student master directory.
    - 'sql': Execute validated read-only SQL SELECT statement.
    """
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
