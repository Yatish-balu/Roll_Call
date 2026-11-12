import os
import sys
from logging.config import fileConfig

from dotenv import load_dotenv
from sqlalchemy import engine_from_config
from sqlalchemy import pool
from sqlalchemy import text

from alembic import context

# Load the repository .env so CLI runs (`alembic upgrade head`) see
# DATABASE_URL_SYNC without requiring the operator to export it manually.
_REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
for _env_file in (os.path.join(os.getcwd(), ".env"), os.path.join(_REPO_ROOT, ".env")):
    if os.path.exists(_env_file):
        load_dotenv(dotenv_path=_env_file, override=False)

# Ensure project root is on sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app.db.base import Base
import app.db.models  # Ensure models are loaded into Base.metadata

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# Resolve the migration URL. Supabase is the only supported runtime backend, so
# DATABASE_URL_SYNC is required unless a test/tool has explicitly set
# sqlalchemy.url on the Config object (e.g. a disposable SQLite database).
sync_db_url = (os.getenv("DATABASE_URL_SYNC") or "").strip()
current_url = config.get_main_option("sqlalchemy.url")
is_default_postgres_url = bool(current_url) and "localhost:5432/postgres" in current_url
is_explicit_url = bool(current_url) and not is_default_postgres_url

if is_explicit_url:
    # Tests/tooling set a dedicated URL (often SQLite); respect it verbatim.
    pass
elif sync_db_url:
    config.set_main_option("sqlalchemy.url", sync_db_url)
else:
    raise RuntimeError(
        "DATABASE_URL_SYNC is not configured. Supabase is the only supported "
        "backend; set DATABASE_URL_SYNC to a postgresql+psycopg:// URL. "
        "Tests must pass an explicit sqlalchemy.url (e.g. a disposable SQLite DB)."
    )



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
            # PRAGMA foreign_keys cannot run inside a SQLite transaction, so
            # execute it on the raw DBAPI connection outside the migration tx.
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

