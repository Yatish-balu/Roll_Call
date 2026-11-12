"""Database synchronization utility between Supabase PostgreSQL and local SQLite.

Usage:
  # Supabase -> SQLite (default): copies all tables safely without duplicates
  python scripts/sync.py

  # SQLite -> Supabase (--init): initial load of all records from SQLite into Supabase
  python scripts/sync.py --init
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path
from typing import Any, Dict, List

# Ensure project root is in sys.path
project_root = Path(__file__).resolve().parent.parent
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

from app.db.connection import (
    DEFAULT_DB_PATH,
    get_connection,
    get_engine,
)
from app.db.schema import init_db

TABLES_IN_ORDER = ["students", "rooms", "sessions", "attendance"]


def _get_sqlite_conn(sqlite_path: str):
    """Return an active SQLite connection with row factory.

    This is an explicit, operator-invoked bridge tool, so it is allowed to open
    SQLite even when the application runs Supabase-only.
    """
    return get_connection(sqlite_path, allow_sqlite=True)


def _get_supabase_engine():
    """Return an active SQLAlchemy engine for Supabase PostgreSQL."""
    db_url = os.getenv("DATABASE_URL_SYNC") or os.getenv("DATABASE_URL")
    if not db_url:
        raise ValueError(
            "DATABASE_URL_SYNC (preferred) or DATABASE_URL must be set in the "
            "environment or .env file."
        )
    engine = get_engine("supabase", db_url=db_url)
    if engine is None:
        raise ConnectionError("Could not create SQLAlchemy engine for Supabase.")
    return engine


def sync_supabase_to_sqlite(sqlite_path: str = DEFAULT_DB_PATH) -> Dict[str, int]:
    """
    Copy all tables from Supabase PostgreSQL to local SQLite.

    Only columns present in both schemas are copied, and rows are upserted on
    each table's real primary key, so reruns are safe and schema changes do not
    break the bridge.
    """
    from sqlalchemy import text

    # Copy order matters for foreign keys.
    tables = (
        ("students", ("usn",)),
        ("rooms", ("room_id",)),
        ("sessions", ("session_id",)),
        ("attendance", ("attendance_id",)),
    )

    engine = _get_supabase_engine()
    sq_conn = _get_sqlite_conn(sqlite_path)
    init_db(sq_conn)

    counts: Dict[str, int] = {}

    try:
        cursor = sq_conn.cursor()
        with engine.connect() as pg_conn:
            for table_name, key_columns in tables:
                sqlite_columns = [
                    row[1]
                    for row in cursor.execute(f"PRAGMA table_info({table_name})").fetchall()
                ]
                pg_res = pg_conn.execute(text(f"SELECT * FROM {table_name}"))
                pg_columns = list(pg_res.keys())
                columns = [c for c in sqlite_columns if c in pg_columns]
                rows = [
                    tuple(r._mapping[c] for c in columns)
                    for r in pg_res
                ]
                if rows:
                    col_list = ", ".join(columns)
                    placeholders = ", ".join("?" for _ in columns)
                    conflict = ", ".join(key_columns)
                    updates = ", ".join(
                        f"{c}=excluded.{c}" for c in columns if c not in key_columns
                    )
                    if updates:
                        statement = (
                            f"INSERT INTO {table_name} ({col_list}) "
                            f"VALUES ({placeholders}) "
                            f"ON CONFLICT({conflict}) DO UPDATE SET {updates}"
                        )
                    else:
                        statement = (
                            f"INSERT INTO {table_name} ({col_list}) "
                            f"VALUES ({placeholders}) "
                            f"ON CONFLICT({conflict}) DO NOTHING"
                        )
                    cursor.executemany(statement, rows)  # nosec B608 - names come from the local schema
                counts[table_name] = len(rows)

        sq_conn.commit()
    finally:
        sq_conn.close()

    return counts


def sync_sqlite_to_supabase(sqlite_path: str = DEFAULT_DB_PATH) -> Dict[str, int]:
    """
    Initial load from local SQLite to Supabase PostgreSQL (--init flag).

    Only columns present in both schemas are copied, and rows are upserted on
    each table's real primary key. This keeps the bridge working as the schema
    evolves (e.g. attendance.attendance_id / recorded_at) and makes reruns safe.
    """
    from sqlalchemy import MetaData, Table
    from sqlalchemy.dialects.postgresql import insert as pg_insert

    # Copy order matters for foreign keys.
    tables = (
        ("students", ("usn",)),
        ("rooms", ("room_id",)),
        ("sessions", ("session_id",)),
        ("attendance", ("attendance_id",)),
    )

    sq_conn = _get_sqlite_conn(sqlite_path)
    engine = _get_supabase_engine()
    init_db(engine)

    counts: Dict[str, int] = {}
    metadata = MetaData()

    try:
        with engine.begin() as pg_conn:
            cursor = sq_conn.cursor()

            for table_name, key_columns in tables:
                pg_table = Table(table_name, metadata, autoload_with=pg_conn)
                pg_columns = {c.name for c in pg_table.columns}
                sqlite_columns = [
                    row[1]
                    for row in cursor.execute(f"PRAGMA table_info({table_name})").fetchall()
                ]
                columns = [c for c in sqlite_columns if c in pg_columns]
                if not columns:
                    counts[table_name] = 0
                    continue

                selected = ", ".join(columns)
                rows = [
                    dict(r)
                    for r in cursor.execute(
                        f"SELECT {selected} FROM {table_name}"
                    ).fetchall()
                ]
                if not rows:
                    counts[table_name] = 0
                    continue

                stmt = pg_insert(pg_table).values(rows)
                update_columns = {
                    c: stmt.excluded[c] for c in columns if c not in key_columns
                }
                if update_columns:
                    stmt = stmt.on_conflict_do_update(
                        index_elements=[pg_table.c[k] for k in key_columns],
                        set_=update_columns,
                    )
                else:
                    stmt = stmt.on_conflict_do_nothing(
                        index_elements=[pg_table.c[k] for k in key_columns]
                    )

                pg_conn.execute(stmt)
                counts[table_name] = len(rows)
    finally:
        sq_conn.close()

    return counts


def main():
    parser = argparse.ArgumentParser(description="Synchronize tables between Supabase PostgreSQL and SQLite.")
    parser.add_argument(
        "--init",
        action="store_true",
        help="Initial load: Copy all records from SQLite to Supabase PostgreSQL.",
    )
    parser.add_argument(
        "--sqlite-path",
        default=DEFAULT_DB_PATH,
        help=f"Path to local SQLite database (default: {DEFAULT_DB_PATH})",
    )
    args = parser.parse_args()

    try:
        if args.init:
            counts = sync_sqlite_to_supabase(args.sqlite_path)
            print(f"[+] Initial load (SQLite -> Supabase) completed successfully:")
            for tbl, cnt in counts.items():
                print(f"    - {tbl}: {cnt} rows synchronized")
        else:
            counts = sync_supabase_to_sqlite(args.sqlite_path)
            print(f"[+] Sync (Supabase -> SQLite) completed successfully:")
            for tbl, cnt in counts.items():
                print(f"    - {tbl}: {cnt} rows synchronized")
    except Exception as exc:
        print(f"[-] Synchronization error: {exc}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()

