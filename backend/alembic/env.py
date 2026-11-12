import os
import sys
from logging.config import fileConfig

from alembic import context
from dotenv import load_dotenv
from sqlalchemy import engine_from_config, pool, text

# Ensure project root is on sys.path and load .env
_BACKEND_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, _BACKEND_DIR)
_ENV_FILE = os.path.join(os.path.dirname(_BACKEND_DIR), ".env")
if os.path.exists(_ENV_FILE):
    load_dotenv(_ENV_FILE)
else:
    load_dotenv()

from app.db.base import Base
import app.db.models  # Ensure models are loaded into Base.metadata

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# Override sqlalchemy.url with environment variable if present.
# When DB_BACKEND is sqlite (or local dev default without an explicit backend),
# target the canonical local SQLite database.
db_backend = os.getenv("DB_BACKEND", "sqlite").strip().lower()
sync_db_url = os.getenv("DATABASE_URL_SYNC")
current_url = config.get_main_option("sqlalchemy.url")
is_default_postgres_url = current_url and "localhost:5432/postgres" in current_url

if db_backend == "sqlite" and (not current_url or is_default_postgres_url):
    from app.db.connection import DEFAULT_DB_PATH
    db_path_posix = DEFAULT_DB_PATH.replace(os.sep, "/") if DEFAULT_DB_PATH != ":memory:" else ":memory:"
    config.set_main_option("sqlalchemy.url", f"sqlite:///{db_path_posix}")
elif sync_db_url and (not current_url or is_default_postgres_url):
    config.set_main_option("sqlalchemy.url", sync_db_url)
elif not current_url or is_default_postgres_url:
    from app.db.connection import DEFAULT_DB_PATH
    db_path_posix = DEFAULT_DB_PATH.replace(os.sep, "/") if DEFAULT_DB_PATH != ":memory:" else ":memory:"
    config.set_main_option("sqlalchemy.url", f"sqlite:///{db_path_posix}")
# Otherwise: current_url is explicitly set (e.g. by tests to a temp SQLite DB) — respect it.



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
        # Disable FK enforcement during migrations to prevent cascade data loss
        # when rebuilding tables (e.g. attendance surrogate->composite PK changes).
        # PRAGMA foreign_keys cannot run inside a SQLite transaction, so execute
        # it on the raw DBAPI connection outside the migration transaction.
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

