"""Query tool for safe, read-only database inspections and analytics.

Enforces read-only operations, parameterized queries, and strict validation
against SQL injection, multi-statement executions, schema mutations, and
unauthorized table access across both Supabase and SQLite backends.

Supports:
1. SQLite local database file paths and sqlite3 Connections (with ?mode=ro).
2. Supabase PostgreSQL via READONLY_DATABASE_URL / DATABASE_URL.
3. Modern SQLAlchemy 2.0 synchronous Session objects.
"""

from __future__ import annotations

import os
import re
import sqlite3
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Set, Tuple, Union

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

# Table references inside a SELECT statement (used for validation and for the
# authorization rewrite of raw SQL). A reference may be plain, quoted
# (`"t"`, `` `t` ``, `[t]`) or schema-qualified (`main.t`); the quoted and
# qualified forms are rejected, because the scope rewrite below only rewrites
# plain identifiers. Accepting them would let a caller read a table with the
# row-level scope silently skipped.
_TABLE_REF_RE = re.compile(r"\b(?:FROM|JOIN)\s+([a-zA-Z0-9_]+)", re.IGNORECASE)
_TABLE_REF_WITH_QUOTES_RE = re.compile(
    r"\b(?:FROM|JOIN)\s+(?P<ref>\"[^\"]*\"|`[^`]*`|\[[^\]]*\]|[A-Za-z0-9_.]+)",
    re.IGNORECASE,
)


def _table_references(sql: str) -> List[str]:
    """Return every table reference following FROM/JOIN, quotes included."""
    return [match.group("ref") for match in _TABLE_REF_WITH_QUOTES_RE.finditer(sql)]


def _reject_non_plain_table_reference(raw_ref: str) -> None:
    """Reject quoted or schema-qualified table references (fail closed)."""
    if not raw_ref:
        return
    if raw_ref[0] in ('"', "`", "["):
        raise ValueError(
            f"Quoted table identifiers are not permitted: {raw_ref!r}. "
            "Reference tables by their plain name."
        )
    if "." in raw_ref:
        raise ValueError(
            f"Schema-qualified table names are not permitted: {raw_ref!r}."
        )


def _scope_clause(
    scope: Any,
    table: str,
    params: Dict[str, Any],
    db: Any = None,
) -> Optional[str]:
    """Return a scoped replacement for a table reference, or None.

    The replacement is a sub-select restricted to the caller's scope, so the
    restriction is applied by the database engine and not by the caller (or by
    the model) afterwards.
    """
    if scope is None or getattr(scope, "unrestricted", False):
        return None

    session_ids = sorted(scope.visible_session_ids(db)) if db is not None else []
    if not session_ids:
        # No visible session: the table is empty for this caller.
        # nosec B608 - table names are restricted to ALLOWED_TABLES by _validate_sql.
        return "(SELECT * FROM {t} WHERE 1 = 0)".format(t=table)  # nosec B608

    sess_params = []
    placeholders = []
    for idx, sid in enumerate(session_ids):
        key = f"{table}_sid_{idx}"
        sess_params.append((key, sid))
        placeholders.append(f":{key}")
    sess_list = ", ".join(placeholders)
    params.update(dict(sess_params))

    codes = sorted(getattr(scope, "subject_codes", frozenset()) or frozenset())
    code_clause = ""
    if codes:
        code_placeholders = []
        for idx, code in enumerate(codes):
            key = f"{table}_code_{idx}"
            params[key] = code
            code_placeholders.append(f":{key}")
        code_clause = (
            " OR usn IN (SELECT st.usn FROM students st "  # nosec B608 - generated ':' placeholders, values bound
            "JOIN subjects sub ON st.dept_id = sub.dept_id "
            f"WHERE UPPER(sub.subject_code) IN ({', '.join(code_placeholders)}))"
        )

    if table == "attendance":
        return (
            f"(SELECT * FROM attendance WHERE session_id IN ({sess_list}) "  # nosec B608 - generated placeholders, values bound
            f"AND usn IN (SELECT a.usn FROM attendance a "
            f"WHERE a.session_id IN ({sess_list})){code_clause})"
        )
    if table == "sessions":
        return f"(SELECT * FROM sessions WHERE session_id IN ({sess_list}))"  # nosec B608 - generated placeholders, values bound
    if table == "students":
        return (
            f"(SELECT * FROM students WHERE usn IN (SELECT a.usn FROM attendance a "  # nosec B608 - generated placeholders, values bound
            f"WHERE a.session_id IN ({sess_list})){code_clause})"
        )
    # rooms carry no session link; they are reference data, not attendance.
    return None


def _apply_scope_to_sql(sql: str, scope: Any, db: Any = None) -> Tuple[str, Dict[str, Any]]:
    """Rewrite a validated SELECT so that it can only read the caller's scope."""
    if scope is None or getattr(scope, "unrestricted", False):
        return sql, {}

    # Defence in depth: never rewrite a statement whose table references the
    # scope rewrite cannot see (quoted / schema-qualified names, or a comment
    # used as a separator).
    if "--" in sql or "/*" in sql:
        raise ValueError("SQL comments are not permitted.")
    for raw_ref in _table_references(sql):
        _reject_non_plain_table_reference(raw_ref)

    params: Dict[str, Any] = {}
    tables = {t.lower() for t in _TABLE_REF_RE.findall(sql)}
    scoped_tables = tables & {"attendance", "sessions", "students"}
    if not scoped_tables:
        # Nothing session- or student-scoped is referenced.
        return sql, params

    def _replace(match: "re.Match[str]") -> str:
        keyword = match.group(1).upper()
        table = match.group(2)
        replacement = _scope_clause(scope, table.lower(), params, db)
        if replacement is None:
            return match.group(0)
        return f"{keyword} {replacement}"

    rewritten = re.sub(
        r"\b(FROM|JOIN)\s+(attendance|sessions|students)\b",
        _replace,
        sql,
        flags=re.IGNORECASE,
    )
    return rewritten, params



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


def _normalize_postgres_url(raw: str) -> str:
    """Normalize a PostgreSQL URL to the project-standard psycopg v3 driver.

    ``postgresql://`` makes SQLAlchemy default to psycopg2, whose connect-time
    catalogue introspection can fail against a transaction-mode pooler. The
    application uses psycopg v3 everywhere else, so pin it explicitly here too.
    """
    if raw.startswith("postgres://"):
        raw = "postgresql://" + raw[len("postgres://"):]
    if raw.startswith("postgresql://"):
        raw = "postgresql+psycopg://" + raw[len("postgresql://"):]
    return raw


class _ReadOnlyDB:
    """Unified read-only connection wrapper for SQLite or Supabase (SQLAlchemy)."""

    def __init__(self, mode: str, conn: Any, should_close: bool = True, engine: Any = None):
        self.mode = mode
        self.conn = conn
        self.should_close = should_close
        self.engine = engine

    def execute(self, sql: str, params: Union[Tuple[Any, ...], List[Any], Dict[str, Any]] = ()):
        if self.mode == "sqlalchemy":
            from sqlalchemy import text
            if isinstance(params, (list, tuple)):
                p_dict = {f"p{i}": v for i, v in enumerate(params)}
                named_sql = sql
                for i in range(len(params)):
                    named_sql = re.sub(r"\?", f":p{i}", named_sql, count=1)
                return self.conn.execute(text(named_sql), p_dict)
            else:
                return self.conn.execute(text(sql), params or {})
        else:
            cursor = self.conn.cursor()
            p = tuple(params) if isinstance(params, (list, tuple)) else params
            cursor.execute(sql, p)
            return cursor

    def close(self):
        if self.should_close:
            try:
                self.conn.close()
            except Exception:
                pass
        if self.engine is not None:
            try:
                self.engine.dispose()
            except Exception:
                pass


def _get_readonly_conn(
    db_target: Union[str, sqlite3.Connection, Any] = DEFAULT_DB_PATH
) -> _ReadOnlyDB:
    """
    Get a read-only database connection.
    In supabase mode: uses READONLY_DATABASE_URL (or DATABASE_URL).
    In sqlite mode: opens the file strictly in read-only URI mode (?mode=ro).
    Also transparently supports SQLAlchemy Session instances.
    """
    # 1. Existing sqlite3.Connection
    if isinstance(db_target, sqlite3.Connection):
        return _ReadOnlyDB("sqlite", db_target, should_close=False)

    # 2. Existing SQLAlchemy Session or Connection
    if hasattr(db_target, "execute") and (hasattr(db_target, "commit") or hasattr(db_target, "flush")):
        return _ReadOnlyDB("sqlalchemy", db_target, should_close=False)

    # 3. Check backend first if default or supabase target
    backend = get_backend()
    if backend == "supabase" and (db_target == DEFAULT_DB_PATH or db_target == "default"):
        ro_url = os.getenv("READONLY_DATABASE_URL") or os.getenv("DATABASE_URL", DATABASE_URL)
        if not ro_url:
            raise ConnectionError("Database connection failed: READONLY_DATABASE_URL or DATABASE_URL not configured.")
        try:
            from sqlalchemy import create_engine
            ro_url = _normalize_postgres_url(ro_url)
            engine_kwargs: Dict[str, Any] = {"pool_pre_ping": True}
            connect_args: Dict[str, Any] = {}
            is_local = "localhost" in ro_url or "127.0.0.1" in ro_url
            if "sslmode=" not in ro_url and not is_local:
                # Supabase requires TLS. psycopg v3 takes sslmode via connect_args.
                connect_args["sslmode"] = "require"
            if "connect_timeout=" not in ro_url:
                # Never hang indefinitely when the database is unreachable or
                # credentials are unavailable; surface a clear ConnectionError.
                connect_args["connect_timeout"] = int(os.getenv("DB_CONNECT_TIMEOUT", "10"))
            if connect_args:
                engine_kwargs["connect_args"] = connect_args
            engine = create_engine(ro_url, **engine_kwargs)
            conn = engine.connect()
            return _ReadOnlyDB("sqlalchemy", conn, should_close=True, engine=engine)
        except Exception as exc:
            raise ConnectionError(f"Database connection failed: {exc}")

    # 4. Check if a custom non-default sqlite path or :memory: was passed
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

    # 5. SQLite default path
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
        elif isinstance(r, sqlite3.Row):
            results.append(dict(r))
        else:
            try:
                results.append(dict(r))
            except Exception:
                results.append(r)
    return results


def validate_read_only_sql(sql: str) -> None:
    """Validate that SQL is strictly read-only, targets allowed tables, and lacks harmful constructs."""
    clean_sql = sql.strip().rstrip(";")
    if not clean_sql:
        raise ValueError("SQL statement cannot be empty.")

    # Comments can hide a table reference from the allowlist and the scope
    # rewrite (`SELECT * FROM/**/users` is valid SQLite), so they are rejected
    # outright. The read-only tool never needs them.
    if "--" in clean_sql or "/*" in clean_sql:
        raise ValueError("SQL comments are not permitted.")

    # Disallow multiple statements
    if ";" in clean_sql:
        raise ValueError("Multiple SQL statements are not permitted.")

    # Check for disallowed mutating keywords
    match = DISALLOWED_SQL_KEYWORDS.search(clean_sql)
    if match:
        raise ValueError(f"Disallowed keyword: '{match.group(0).upper()}'. Only SELECT or WITH queries are permitted.")

    # Enforce SELECT query
    if not re.match(r"^(SELECT|WITH)\b", clean_sql, re.IGNORECASE):
        raise ValueError("Only SELECT or WITH queries are permitted. Disallowed keyword.")

    # Extract and validate table names. Quoted identifiers are rejected before
    # the allowlist check: `FROM "attendance"` used to slip past both the
    # allowlist and the scope rewrite, exposing every session's rows.
    for raw_ref in _table_references(clean_sql):
        _reject_non_plain_table_reference(raw_ref)
        table = raw_ref.lower()
        if table not in ALLOWED_TABLES:
            raise ValueError(f"Access to table '{table}' is not permitted.")


def _normalize_scoped_params(
    sql: str,
    params: Union[Tuple[Any, ...], List[Any], Dict[str, Any]],
    scope_params: Dict[str, Any],
) -> Tuple[str, Dict[str, Any]]:
    """Merge the scope parameters with the caller's parameters.

    The scoped statement uses named placeholders, so any positional parameters
    are converted to named ones (``?`` -> ``:p0``, ``:p1`` ...) before they are
    merged.
    """
    if not scope_params:
        return sql, {}

    if isinstance(params, dict):
        merged = dict(params)
        merged.update(scope_params)
        return sql, merged

    positional = list(params or [])
    named: Dict[str, Any] = {}
    rewritten = sql
    for index, value in enumerate(positional):
        key = f"p{index}"
        named[key] = value
        rewritten = re.sub(r"\?", f":{key}", rewritten, count=1)
    named.update(scope_params)
    return rewritten, named


def safe_sql_query(
    sql: str,
    params: Union[Tuple[Any, ...], List[Any], Dict[str, Any]] = (),
    db_target: Union[str, sqlite3.Connection, Any] = DEFAULT_DB_PATH,
    limit: int = 500,
    scope: Any = None,
) -> QueryResult:
    """
    Execute an arbitrary read-only SQL query with safety validation and parameterization.
    Enforces LIMIT clause and returns structured QueryResult.

    When a ``scope`` is supplied the statement is rewritten so that it can only
    read sessions and students inside the caller's scope. The restriction is
    applied by the database engine, not afterwards by the model.
    """
    validate_read_only_sql(sql)

    ro_db = _get_readonly_conn(db_target)
    try:
        # Check if LIMIT already present, otherwise append
        clean_sql = sql.strip().rstrip(";")
        if not re.search(r"\bLIMIT\s+\d+", clean_sql, re.IGNORECASE):
            clean_sql = f"{clean_sql} LIMIT {limit}"

        scoped_sql, scope_params = _apply_scope_to_sql(clean_sql, scope, db_target)
        if scope_params:
            scoped_sql, params = _normalize_scoped_params(scoped_sql, params, scope_params)

        res = ro_db.execute(scoped_sql, params)
        rows = res.fetchall() if hasattr(res, "fetchall") else list(res)
        results = _rows_to_dicts(rows)

        found = len(results) > 0
        message = (
            f"Query executed successfully. Found {len(results)} records."
            if found
            else NO_DATA_MESSAGE
        )
        return QueryResult(
            found=found,
            data=results,
            total_count=len(results),
            message=message,
            metadata={"query": clean_sql, "record_count": len(results)},
        )
    except Exception as exc:
        return QueryResult(
            found=False,
            data=[],
            total_count=0,
            message=f"Query execution error: {exc}",
            metadata={"error": str(exc)},
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
    scope: Any = None,
) -> QueryResult:
    """Query attendance records with optional filtering by session, room, branch, USN, or status.

    When a ``scope`` is supplied, only sessions inside the caller's scope are
    read, and an explicitly requested session outside that scope yields no data
    (the existence of the session is not confirmed).
    """
    # LIMIT is interpolated into the SQL text, so coerce it to a bounded int.
    try:
        limit = max(1, min(1000, int(limit)))
    except (TypeError, ValueError):
        limit = 500

    conditions = []
    params: List[Any] = []

    if scope is not None and not getattr(scope, "unrestricted", False):
        visible = sorted(scope.visible_session_ids(db_target))
        if session_id and session_id.strip() and session_id.strip() not in visible:
            return QueryResult(
                found=False,
                data=[],
                total_count=0,
                message=NO_DATA_MESSAGE,
                metadata={"filters": {"session_id": session_id}},
            )
        if not visible:
            return QueryResult(
                found=False,
                data=[],
                total_count=0,
                message=NO_DATA_MESSAGE,
                metadata={},
            )
        placeholders = ",".join("?" for _ in visible)
        conditions.append(f"a.session_id IN ({placeholders})")
        params.extend(visible)

    if session_id:
        conditions.append("a.session_id = ?")
        params.append(session_id.strip())
    if room_id:
        conditions.append("a.room_id = ?")
        params.append(room_id.strip())
    if usn:
        conditions.append("a.usn = ?")
        params.append(usn.strip())
    if status:
        clean_status = status.strip().upper()
        conditions.append("a.status = ?")
        params.append(clean_status)
    if branch:
        conditions.append("s.branch = ?")
        params.append(branch.strip())

    where_clause = f"WHERE {' AND '.join(conditions)}" if conditions else ""

    sql = f"""
    SELECT
        a.session_id,
        a.usn,
        s.name AS student_name,
        s.branch,
        a.room_id,
        r.name AS room_name,
        a.status,
        a.source,
        a.confidence,
        sess.date,
        sess.subject
    FROM attendance a
    JOIN students s ON a.usn = s.usn
    LEFT JOIN rooms r ON a.room_id = r.room_id
    LEFT JOIN sessions sess ON a.session_id = sess.session_id
    {where_clause}
    ORDER BY a.session_id, a.usn
    LIMIT {limit}
    """  # nosec B608 - where_clause is a fixed clause list, values bound; limit is a bounded int

    ro_db = _get_readonly_conn(db_target)
    try:
        res = ro_db.execute(sql, params)
        rows = res.fetchall() if hasattr(res, "fetchall") else list(res)
        results = _rows_to_dicts(rows)

        found = len(results) > 0
        message = (
            f"Found {len(results)} attendance records."
            if found
            else NO_DATA_MESSAGE
        )
        return QueryResult(
            found=found,
            data=results,
            total_count=len(results),
            message=message,
            metadata={
                "filters": {
                    "session_id": session_id,
                    "room_id": room_id,
                    "branch": branch,
                    "usn": usn,
                    "status": status,
                }
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


def query_student_attendance(
    usn: str,
    db_target: Union[str, sqlite3.Connection, Any] = DEFAULT_DB_PATH,
) -> QueryResult:
    """Retrieve full attendance history and summary stats for a single student."""
    clean_usn = usn.strip()

    ro_db = _get_readonly_conn(db_target)
    try:
        # Check student exists
        sql_student = "SELECT usn, name, branch FROM students WHERE usn = ?"
        res = ro_db.execute(sql_student, (clean_usn,))
        row = res.fetchone()
        if not row:
            return QueryResult(
                found=False,
                data=[],
                total_count=0,
                message=NO_DATA_MESSAGE,
                metadata={"usn": clean_usn, "reason": "student not found"},
            )

        student_info = dict(row._mapping) if hasattr(row, "_mapping") else dict(row)

        sql_records = """
        SELECT
            a.session_id,
            sess.date,
            sess.subject,
            a.room_id,
            a.status,
            a.source,
            a.confidence
        FROM attendance a
        LEFT JOIN sessions sess ON a.session_id = sess.session_id
        WHERE a.usn = ?
        ORDER BY sess.date DESC, a.session_id
        """
        res_records = ro_db.execute(sql_records, (clean_usn,))
        records = _rows_to_dicts(res_records.fetchall() if hasattr(res_records, "fetchall") else list(res_records))

        total_sessions = len(records)
        present_count = sum(1 for r in records if r.get("status") == "PRESENT")
        absent_count = sum(1 for r in records if r.get("status") == "ABSENT")
        pending_count = sum(1 for r in records if r.get("status") == "PENDING")
        unreviewed_count = sum(1 for r in records if r.get("status") == "UNREVIEWED")

        confirmed = present_count + absent_count
        confirmed_percentage = (
            round((present_count / confirmed) * 100, 2) if confirmed > 0 else 0.0
        )
        overall_percentage = (
            round((present_count / total_sessions) * 100, 2)
            if total_sessions > 0
            else 0.0
        )

        summary = {
            "usn": clean_usn,
            "name": student_info.get("name"),
            "branch": student_info.get("branch"),
            "total_sessions": total_sessions,
            "present_count": present_count,
            "absent_count": absent_count,
            "pending_count": pending_count,
            "unreviewed_count": unreviewed_count,
            "confirmed_count": confirmed,
            "confirmed_percentage": confirmed_percentage,
            "overall_percentage": overall_percentage,
            "records": records,
        }

        return QueryResult(
            found=True,
            data=[summary],
            total_count=total_sessions,
            message=f"Attendance history found for {student_info.get('name')} ({clean_usn}). Attendance: {confirmed_percentage}%.",
            metadata=summary,
        )
    except Exception as exc:
        return QueryResult(
            found=False,
            data=[],
            total_count=0,
            message=f"Error querying student attendance: {exc}",
            metadata={"usn": clean_usn, "error": str(exc)},
        )
    finally:
        ro_db.close()


def query_students(
    usn: Optional[str] = None,
    branch: Optional[str] = None,
    name: Optional[str] = None,
    limit: int = 500,
    db_target: Union[str, sqlite3.Connection, Any] = DEFAULT_DB_PATH,
    scope: Any = None,
) -> QueryResult:
    """Retrieve students matching optional usn, branch, or name filters.

    When a ``scope`` is supplied only students inside the caller's scope are
    returned.
    """
    # LIMIT is interpolated into the SQL text, so coerce it to a bounded int.
    try:
        limit = max(1, min(1000, int(limit)))
    except (TypeError, ValueError):
        limit = 500

    conditions = []
    params: List[Any] = []

    if scope is not None and not getattr(scope, "unrestricted", False):
        visible = sorted(scope.visible_student_usns(db_target))
        if not visible:
            return QueryResult(
                found=False,
                data=[],
                total_count=0,
                message=NO_DATA_MESSAGE,
                metadata={},
            )
        placeholders = ",".join("?" for _ in visible)
        conditions.append(f"usn IN ({placeholders})")
        params.extend(visible)

    if usn:
        conditions.append("usn = ?")
        params.append(usn.strip())
    if branch:
        conditions.append("branch = ?")
        params.append(branch.strip())
    if name:
        conditions.append("name LIKE ?")
        params.append(f"%{name.strip()}%")

    where_clause = f"WHERE {' AND '.join(conditions)}" if conditions else ""
    sql = f"SELECT usn, name, branch FROM students {where_clause} ORDER BY usn LIMIT {limit}"  # nosec B608 - fixed clause list, values bound, bounded int

    ro_db = _get_readonly_conn(db_target)
    try:
        res = ro_db.execute(sql, params)
        rows = res.fetchall() if hasattr(res, "fetchall") else list(res)
        results = _rows_to_dicts(rows)
        found = len(results) > 0
        message = (
            f"Found {len(results)} students." if found else NO_DATA_MESSAGE
        )
        return QueryResult(
            found=found,
            data=results,
            total_count=len(results),
            message=message,
            metadata={"record_count": len(results)},
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
    scope: Any = None,
) -> QueryResult:
    """Calculate aggregated attendance metrics for a specific session.

    When a ``scope`` is supplied, a session outside the caller's scope is
    reported as "no data" instead of confirming that it exists.
    """
    clean_id = session_id.strip()

    if scope is not None and not getattr(scope, "unrestricted", False):
        visible = sorted(scope.visible_session_ids(db_target))
        if clean_id not in visible:
            return QueryResult(
                found=False,
                data=[],
                total_count=0,
                message=NO_DATA_MESSAGE,
                metadata={"session_id": clean_id},
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
        status_rows = res_stats.fetchall() if hasattr(res_stats, "fetchall") else list(res_stats)
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
    scope: Any = None,
) -> QueryResult:
    """Retrieve absent students for a given session or room/branch combination."""
    return query_attendance(
        session_id=session_id,
        room_id=room_id,
        branch=branch,
        status="ABSENT",
        limit=limit,
        db_target=db_target,
        scope=scope,
    )


def query_tool(
    query_type: str = "attendance",
    session_id: Optional[str] = None,
    room_id: Optional[str] = None,
    branch: Optional[str] = None,
    usn: Optional[str] = None,
    status: Optional[str] = None,
    sql: Optional[str] = None,
    params: Optional[Union[Tuple[Any, ...], List[Any], Dict[str, Any]]] = None,
    limit: int = 500,
    db_target: Union[str, sqlite3.Connection, Any] = DEFAULT_DB_PATH,
    scope: Any = None,
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
            scope=scope,
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
        return query_session_stats(
            session_id=session_id, db_target=db_target, scope=scope
        )
    if clean_type in ("absentees", "absent"):
        return query_absentees(
            session_id=session_id,
            room_id=room_id,
            branch=branch,
            limit=limit,
            db_target=db_target,
            scope=scope,
        )
    if clean_type in ("students", "student"):
        return query_students(
            usn=usn,
            branch=branch,
            name=kwargs.get("name"),
            limit=limit,
            db_target=db_target,
            scope=scope,
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
            scope=scope,
        )

    return QueryResult(
        found=False,
        data=[],
        total_count=0,
        message=f"Unsupported query_type '{query_type}'. Allowed: attendance, session_stats, absentees, students, sql.",
        metadata={"query_type": query_type},
    )
