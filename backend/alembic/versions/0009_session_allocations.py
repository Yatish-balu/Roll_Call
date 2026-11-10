"""Session allocations and session lifecycle fields.

Revision ID: 0009_session_allocations
Revises: 0008_timetables
Create Date: 2026-11-10 10:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "0009_session_allocations"
down_revision: Union[str, None] = "0008_timetables"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. Add lifecycle_status and coordinator_faculty_id to sessions
    op.add_column(
        "sessions",
        sa.Column("lifecycle_status", sa.String(), nullable=False, server_default="SCHEDULED"),
    )
    op.add_column(
        "sessions",
        sa.Column("coordinator_faculty_id", sa.String(), nullable=True),
    )
    op.create_index("idx_sessions_lifecycle", "sessions", ["lifecycle_status"], unique=False)

    # 2. Create session_allocations table
    op.create_table(
        "session_allocations",
        sa.Column("allocation_id", sa.String(), nullable=False),
        sa.Column("session_id", sa.String(), nullable=False),
        sa.Column("timetable_entry_id", sa.String(), nullable=True),
        sa.Column("allocation_date", sa.String(), nullable=False),
        sa.Column("room_id", sa.String(), nullable=False),
        sa.Column("start_time", sa.String(), nullable=False),
        sa.Column("end_time", sa.String(), nullable=False),
        sa.Column("batch_id", sa.String(), nullable=True),
        sa.Column("faculty_id", sa.String(), nullable=True),
        sa.Column("lifecycle_status", sa.String(), nullable=False, server_default="SCHEDULED"),
        sa.Column("created_at", sa.String(), nullable=False),
        sa.ForeignKeyConstraint(
            ["session_id"],
            ["sessions.session_id"],
            name="fk_session_allocations_session_id",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["timetable_entry_id"],
            ["timetable_entries.entry_id"],
            name="fk_session_allocations_timetable_entry_id",
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["room_id"],
            ["rooms.room_id"],
            name="fk_session_allocations_room_id",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["batch_id"],
            ["batches.batch_id"],
            name="fk_session_allocations_batch_id",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["faculty_id"],
            ["users.user_id"],
            name="fk_session_allocations_faculty_id",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("allocation_id", name="pk_session_allocations"),
    )
    op.create_index("idx_session_allocations_session_id", "session_allocations", ["session_id"], unique=False)
    op.create_index("idx_session_allocations_allocation_date", "session_allocations", ["allocation_date"], unique=False)
    op.create_index("idx_session_allocations_room_id", "session_allocations", ["room_id"], unique=False)
    op.create_index("idx_session_allocations_faculty_id", "session_allocations", ["faculty_id"], unique=False)
    op.create_index("idx_session_allocations_batch_id", "session_allocations", ["batch_id"], unique=False)
    op.create_index("idx_session_allocations_lifecycle", "session_allocations", ["lifecycle_status"], unique=False)

    # 3. Add FK for coordinator_faculty_id using batch mode (SQLite compatibility)
    with op.batch_alter_table("sessions") as batch_op:
        batch_op.create_foreign_key(
            "fk_sessions_coordinator_faculty_id",
            "users",
            ["coordinator_faculty_id"],
            ["user_id"],
            ondelete="RESTRICT",
        )


def downgrade() -> None:
    with op.batch_alter_table("sessions") as batch_op:
        batch_op.drop_constraint("fk_sessions_coordinator_faculty_id", type_="foreignkey")
        batch_op.drop_index("idx_sessions_lifecycle")
        batch_op.drop_column("coordinator_faculty_id")
        batch_op.drop_column("lifecycle_status")

    op.drop_index("idx_session_allocations_lifecycle", table_name="session_allocations")
    op.drop_index("idx_session_allocations_batch_id", table_name="session_allocations")
    op.drop_index("idx_session_allocations_faculty_id", table_name="session_allocations")
    op.drop_index("idx_session_allocations_room_id", table_name="session_allocations")
    op.drop_index("idx_session_allocations_allocation_date", table_name="session_allocations")
    op.drop_index("idx_session_allocations_session_id", table_name="session_allocations")
    op.drop_table("session_allocations")
