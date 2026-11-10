"""Attendance surrogate primary key and allocation_id.

Revision ID: 0010_attendance_surrogate_pk
Revises: 0009_session_allocations
Create Date: 2026-11-10 10:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "0010_attendance_surrogate_pk"
down_revision: Union[str, None] = "0009_session_allocations"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _is_sqlite() -> bool:
    bind = op.get_bind()
    return bind.dialect.name == "sqlite"


def upgrade() -> None:
    if _is_sqlite():
        # SQLite: recreate table with new schema (batch mode for PK change)
        op.add_column("attendance", sa.Column("attendance_id", sa.String(), nullable=True))
        op.add_column("attendance", sa.Column("allocation_id", sa.String(), nullable=True))

        # Backfill UUIDs
        op.execute(
            "UPDATE attendance SET attendance_id = lower(hex(randomblob(16))) WHERE attendance_id IS NULL"
        )

        # Verify no NULLs
        conn = op.get_bind()
        null_count = conn.execute(
            sa.text("SELECT COUNT(*) FROM attendance WHERE attendance_id IS NULL")
        ).scalar()
        if null_count > 0:
            raise RuntimeError(f"{null_count} attendance rows missing attendance_id after backfill")

        # Create new table with surrogate PK
        op.create_table(
            "attendance_new",
            sa.Column("attendance_id", sa.String(), primary_key=True),
            sa.Column("session_id", sa.String(), nullable=False),
            sa.Column("allocation_id", sa.String(), nullable=True),
            sa.Column("usn", sa.String(), nullable=False),
            sa.Column("room_id", sa.String(), nullable=False),
            sa.Column("status", sa.String(), nullable=False),
            sa.Column("source", sa.String(), nullable=False),
            sa.Column("confidence", sa.Float(), nullable=False, default=1.0),
            sa.Column("recorded_at", sa.String(), nullable=False),
            sa.CheckConstraint(
                "status IN ('PRESENT', 'ABSENT', 'PENDING', 'UNREVIEWED')",
                name="check_attendance_status",
            ),
            sa.ForeignKeyConstraint(
                ["session_id"], ["sessions.session_id"], name="fk_attendance_session_id", ondelete="CASCADE"
            ),
            sa.ForeignKeyConstraint(
                ["usn"], ["students.usn"], name="fk_attendance_usn", ondelete="CASCADE"
            ),
            sa.ForeignKeyConstraint(
                ["room_id"], ["rooms.room_id"], name="fk_attendance_room_id", ondelete="RESTRICT"
            ),
            sa.ForeignKeyConstraint(
                ["allocation_id"],
                ["session_allocations.allocation_id"],
                name="fk_attendance_allocation_id",
                ondelete="SET NULL",
            ),
        )

        # Copy data (recorded_at defaults to created_at equivalent for legacy rows)
        op.execute(
            """
            INSERT INTO attendance_new (attendance_id, session_id, allocation_id, usn, room_id, status, source, confidence, recorded_at)
            SELECT attendance_id, session_id, allocation_id, usn, room_id, status, source, confidence,
                   strftime('%Y-%m-%dT%H:%M:%SZ', 'now')
            FROM attendance
            """
        )

        # Drop old, rename
        op.drop_table("attendance")
        op.rename_table("attendance_new", "attendance")

        # Create indexes
        op.create_index("idx_attendance_session", "attendance", ["session_id"], unique=False)
        op.create_index("idx_attendance_usn", "attendance", ["usn"], unique=False)
        op.create_index("idx_attendance_room", "attendance", ["room_id"], unique=False)
        op.create_index("idx_attendance_allocation", "attendance", ["allocation_id"], unique=False)

        # Partial unique indexes
        op.execute(
            "CREATE UNIQUE INDEX idx_attendance_allocation_usn ON attendance (allocation_id, usn) WHERE allocation_id IS NOT NULL"
        )
        op.execute(
            "CREATE UNIQUE INDEX idx_attendance_legacy_session_usn ON attendance (session_id, usn) WHERE allocation_id IS NULL"
        )
    else:
        # PostgreSQL: ALTER TABLE approach
        op.add_column(
            "attendance",
            sa.Column("attendance_id", sa.String(), nullable=True),
        )
        op.add_column(
            "attendance",
            sa.Column("allocation_id", sa.String(), nullable=True),
        )

        # Backfill UUIDs
        op.execute(
            "UPDATE attendance SET attendance_id = gen_random_uuid()::text WHERE attendance_id IS NULL"
        )

        # Verify no NULLs
        conn = op.get_bind()
        null_count = conn.execute(
            sa.text("SELECT COUNT(*) FROM attendance WHERE attendance_id IS NULL")
        ).scalar()
        if null_count > 0:
            raise RuntimeError(f"{null_count} attendance rows missing attendance_id after backfill")

        # Enforce NOT NULL and PK
        op.alter_column("attendance", "attendance_id", nullable=False, existing_type=sa.String())
        op.create_primary_key("pk_attendance", "attendance", ["attendance_id"])
        op.create_foreign_key(
            "fk_attendance_allocation_id",
            "attendance",
            "session_allocations",
            ["allocation_id"],
            ["allocation_id"],
            ondelete="SET NULL",
        )

        # Partial unique indexes
        op.create_index(
            "idx_attendance_allocation_usn",
            "attendance",
            ["allocation_id", "usn"],
            unique=True,
            postgresql_where=sa.text("allocation_id IS NOT NULL"),
        )
        op.create_index(
            "idx_attendance_legacy_session_usn",
            "attendance",
            ["session_id", "usn"],
            unique=True,
            postgresql_where=sa.text("allocation_id IS NULL"),
        )


def downgrade() -> None:
    if _is_sqlite():
        # Drop indexes
        op.drop_index("idx_attendance_legacy_session_usn", table_name="attendance")
        op.drop_index("idx_attendance_allocation_usn", table_name="attendance")
        op.drop_index("idx_attendance_allocation", table_name="attendance")
        op.drop_index("idx_attendance_room", table_name="attendance")
        op.drop_index("idx_attendance_usn", table_name="attendance")
        op.drop_index("idx_attendance_session", table_name="attendance")

        # Recreate old table
        op.create_table(
            "attendance_old",
            sa.Column("session_id", sa.String(), nullable=False),
            sa.Column("usn", sa.String(), nullable=False),
            sa.Column("room_id", sa.String(), nullable=False),
            sa.Column("status", sa.String(), nullable=False),
            sa.Column("source", sa.String(), nullable=False),
            sa.Column("confidence", sa.Float(), nullable=False, default=1.0),
            sa.PrimaryKeyConstraint("session_id", "usn", name="pk_attendance"),
            sa.CheckConstraint(
                "status IN ('PRESENT', 'ABSENT', 'PENDING', 'UNREVIEWED')",
                name="check_attendance_status",
            ),
            sa.ForeignKeyConstraint(
                ["session_id"], ["sessions.session_id"], name="fk_attendance_session_id", ondelete="CASCADE"
            ),
            sa.ForeignKeyConstraint(
                ["usn"], ["students.usn"], name="fk_attendance_usn", ondelete="CASCADE"
            ),
            sa.ForeignKeyConstraint(
                ["room_id"], ["rooms.room_id"], name="fk_attendance_room_id", ondelete="RESTRICT"
            ),
        )

        # Copy legacy data (session_id, usn, status, source, confidence)
        op.execute(
            """
            INSERT INTO attendance_old (session_id, usn, room_id, status, source, confidence)
            SELECT session_id, usn, room_id, status, source, confidence
            FROM attendance
            """
        )

        op.drop_table("attendance")
        op.rename_table("attendance_old", "attendance")

        op.create_index("idx_attendance_session", "attendance", ["session_id"], unique=False)
        op.create_index("idx_attendance_usn", "attendance", ["usn"], unique=False)
        op.create_index("idx_attendance_room", "attendance", ["room_id"], unique=False)
    else:
        op.drop_index("idx_attendance_legacy_session_usn", table_name="attendance")
        op.drop_index("idx_attendance_allocation_usn", table_name="attendance")
        op.drop_constraint("fk_attendance_allocation_id", table_name="attendance", type_="foreignkey")
        op.drop_constraint("pk_attendance", table_name="attendance", type_="primary")
        op.drop_column("attendance", "allocation_id")
        op.drop_column("attendance", "attendance_id")
