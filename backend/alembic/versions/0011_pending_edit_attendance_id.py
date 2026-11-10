"""PendingEdit: replace session_id/usn FK with attendance_id FK.

Revision ID: 0011_pending_edit_attendance_id
Revises: 0010_attendance_surrogate_pk
Create Date: 2026-11-10 10:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "0011_pending_edit_attendance_id"
down_revision: Union[str, None] = "0010_attendance_surrogate_pk"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _is_sqlite() -> bool:
    bind = op.get_bind()
    return bind.dialect.name == "sqlite"


def upgrade() -> None:
    if _is_sqlite():
        # SQLite: batch mode for FK change
        with op.batch_alter_table("pending_edits") as batch_op:
            batch_op.drop_constraint("fk_pending_edits_attendance", type_="foreignkey")
            batch_op.add_column(
                sa.Column("attendance_id", sa.String(), nullable=True),
            )
            batch_op.create_foreign_key(
                "fk_pending_edits_attendance_id",
                "attendance",
                ["attendance_id"],
                ["attendance_id"],
                ondelete="CASCADE",
            )
    else:
        # PostgreSQL: direct ALTER TABLE
        op.drop_constraint("fk_pending_edits_attendance", table_name="pending_edits", type_="foreignkey")
        op.add_column(
            "pending_edits",
            sa.Column("attendance_id", sa.String(), nullable=True),
        )
        op.create_foreign_key(
            "fk_pending_edits_attendance_id",
            "pending_edits",
            "attendance",
            ["attendance_id"],
            ["attendance_id"],
            ondelete="CASCADE",
        )


def downgrade() -> None:
    if _is_sqlite():
        # Clean up any leftover temp table from previous interrupted batch operations
        op.execute("DROP TABLE IF EXISTS _alembic_tmp_pending_edits")
        with op.batch_alter_table("pending_edits") as batch_op:
            batch_op.drop_constraint("fk_pending_edits_attendance_id", type_="foreignkey")
            batch_op.drop_column("attendance_id")
            # NOTE: Do NOT recreate the old fk_pending_edits_attendance FK on
            # attendance(session_id, usn) here. At downgrade time the attendance
            # table still uses attendance_id as its PK (from 0010); the composite
            # (session_id, usn) PK only exists after 0010's own downgrade runs.
            # Recreating this FK now causes "foreign key mismatch" in SQLite
            # batch mode because no matching UNIQUE/PK constraint exists yet.
    else:
        op.drop_constraint("fk_pending_edits_attendance_id", table_name="pending_edits", type_="foreignkey")
        op.drop_column("pending_edits", "attendance_id")
        # NOTE: Same rationale as SQLite branch - do not recreate old FK here.
