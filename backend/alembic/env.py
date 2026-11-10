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
# If not present and config url is unconfigured or points to default postgres placeholder, default to local SQLite DB.
sync_db_url = os.getenv("DATABASE_URL_SYNC")
current_url = config.get_main_option("sqlalchemy.url")
if sync_db_url:
    config.set_main_option("sqlalchemy.url", sync_db_url)
elif not current_url or "localhost:5432/postgres" in current_url:
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
        # Disable FK enforcement during migrations to prevent cascade data loss
        # when rebuilding tables (e.g. attendance surrogate->composite PK changes).
        connection.execute(text("PRAGMA foreign_keys = OFF"))
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

