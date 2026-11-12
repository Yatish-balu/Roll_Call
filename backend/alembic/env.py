import os
import sys
from logging.config import fileConfig

from alembic import context
from dotenv import load_dotenv
from sqlalchemy import engine_from_config, pool, text

# Load repository and current working directory .env files so CLI runs see
# DATABASE_URL_SYNC without requiring manual environment export.
_BACKEND_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
_REPO_ROOT = os.path.abspath(os.path.join(_BACKEND_DIR, ".."))
sys.path.insert(0, _BACKEND_DIR)

for _env_file in (
    os.path.join(os.getcwd(), ".env"),
    os.path.join(_BACKEND_DIR, ".env"),
    os.path.join(_REPO_ROOT, ".env"),
):
    if os.path.exists(_env_file):
        load_dotenv(dotenv_path=_env_file, override=False)

from app.db.base import Base
import app.db.models  # Ensure models are loaded into Base.metadata

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# Resolve migration URL:
# 1. Tests/tooling set an explicit sqlalchemy.url on Config -> respect verbatim.
# 2. When DB_BACKEND == "sqlite", target local SQLite DEFAULT_DB_PATH.
# 3. If DATABASE_URL_SYNC is configured, target Supabase PostgreSQL.
# 4. Fallback to local SQLite DEFAULT_DB_PATH.
db_backend = os.getenv("DB_BACKEND", "").strip().lower()
sync_db_url = (os.getenv("DATABASE_URL_SYNC") or "").strip()
current_url = config.get_main_option("sqlalchemy.url")
is_default_postgres_url = bool(current_url) and "localhost:5432/postgres" in current_url
is_explicit_url = bool(current_url) and not is_default_postgres_url

if is_explicit_url:
    # Explicit URL supplied by caller (e.g. test fixture); respect it verbatim
    pass
elif db_backend == "sqlite":
    from app.db.connection import DEFAULT_DB_PATH
    db_path_posix = DEFAULT_DB_PATH.replace(os.sep, "/") if DEFAULT_DB_PATH != ":memory:" else ":memory:"
    config.set_main_option("sqlalchemy.url", f"sqlite:///{db_path_posix}")
elif sync_db_url:
    config.set_main_option("sqlalchemy.url", sync_db_url)
else:
    from app.db.connection import DEFAULT_DB_PATH
    db_path_posix = DEFAULT_DB_PATH.replace(os.sep, "/") if DEFAULT_DB_PATH != ":memory:" else ":memory:"
    config.set_main_option("sqlalchemy.url", f"sqlite:///{db_path_posix}")

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode."""
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Run migrations in 'online' mode."""
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    with connectable.connect() as connection:
        # Disable FK enforcement during SQLite migrations to prevent cascade data
        # loss when rebuilding tables (e.g. attendance surrogate->composite PK
        # changes). PRAGMA is SQLite-only: issuing it on PostgreSQL aborts the
        # transaction, so it must never run against Supabase.
        if connection.dialect.name == "sqlite":
            raw_dbapi_conn = connection.connection
            try:
                cursor = raw_dbapi_conn.cursor()
                cursor.execute("PRAGMA foreign_keys = OFF")
                cursor.close()
            except Exception:
                pass

        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            compare_type=True,
        )

        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
