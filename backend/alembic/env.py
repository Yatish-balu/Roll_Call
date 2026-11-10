import os
import sys
from logging.config import fileConfig

from sqlalchemy import engine_from_config
from sqlalchemy import pool
from sqlalchemy import text

from alembic import context

# Ensure project root is on sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app.db.base import Base
import app.db.models  # Ensure models are loaded into Base.metadata

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# Override sqlalchemy.url with environment variable if present.
# Only override when the current URL is the default alembic.ini postgres placeholder
# or when no URL was explicitly configured. Tests that set sqlalchemy.url directly
# on the Config object (e.g. to a temporary SQLite DB) must be respected.
sync_db_url = os.getenv("DATABASE_URL_SYNC")
current_url = config.get_main_option("sqlalchemy.url")
is_default_postgres_url = current_url and "localhost:5432/postgres" in current_url
if sync_db_url and (not current_url or is_default_postgres_url):
    # DATABASE_URL_SYNC configured and no explicit URL (or only default placeholder): use it
    config.set_main_option("sqlalchemy.url", sync_db_url)
elif not current_url or is_default_postgres_url:
    # No URL or only the default postgres placeholder: fall back to local SQLite
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

