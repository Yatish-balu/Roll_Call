"""Add the descriptive user profile table (Profile Settings persistence).

The Profile Settings UI previously had no server-side storage: its
``PUT /api/v1/profile`` probe hit a non-existent endpoint and the client fell
back to device-local storage, so edits never reached the database. This adds
the 1:1 ``user_profiles`` table backing ``GET/PUT/PATCH /api/v1/me/profile``.

Display name and email stay on ``users`` (``users.name`` / ``users.email``);
this table holds the descriptive fields only.

Revision ID: 0019_user_profiles
Revises: 0018_performance_indexes
Create Date: 2026-11-13
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy import text

revision = "0019_user_profiles"
down_revision = "0018_performance_indexes"
branch_labels = None
depends_on = None

# Matches the shape already in use by live environments (which created the
# table manually before this migration existed), so the migration is a no-op
# there and canonical on fresh databases.
_CREATE_SQL = """
CREATE TABLE IF NOT EXISTS user_profiles (
    user_id VARCHAR NOT NULL PRIMARY KEY,
    full_name VARCHAR,
    mobile VARCHAR,
    email VARCHAR,
    branch VARCHAR,
    designation VARCHAR,
    experience_years INTEGER,
    qualifications VARCHAR,
    specialization VARCHAR,
    expertise TEXT,
    mastered_subjects TEXT,
    photo_url TEXT,
    updated_at VARCHAR,
    CONSTRAINT fk_user_profiles_user_id FOREIGN KEY(user_id) REFERENCES users (user_id) ON DELETE CASCADE
)
"""

_FK_SQL = """
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.table_constraints
        WHERE constraint_type = 'FOREIGN KEY'
          AND table_name = 'user_profiles'
          AND constraint_name = 'fk_user_profiles_user_id'
    ) THEN
        ALTER TABLE user_profiles
            ADD CONSTRAINT fk_user_profiles_user_id
            FOREIGN KEY (user_id) REFERENCES users (user_id) ON DELETE CASCADE;
    END IF;
END $$;
"""


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "sqlite":
        # SQLite path (disposable test databases): batch-safe plain create.
        op.execute(_CREATE_SQL)
        return
    op.execute(_CREATE_SQL)
    try:
        op.execute(_FK_SQL)
    except Exception:
        # A pre-existing table may hold rows whose user_id no longer matches
        # users; the FK is an integrity nicety, not worth failing startup for.
        pass


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS user_profiles")
