"""Initial schema creation matching RollCall AI database.

Revision ID: 0001_initial_schema
Revises: 
Create Date: 2026-11-07 23:18:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "0001_initial_schema"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. students table
    op.create_table(
        "students",
        sa.Column("usn", sa.String(), nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("branch", sa.String(), nullable=False),
        sa.PrimaryKeyConstraint("usn", name="pk_students"),
    )

    # 2. rooms table
    op.create_table(
        "rooms",
        sa.Column("room_id", sa.String(), nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.PrimaryKeyConstraint("room_id", name="pk_rooms"),
    )

    # 3. sessions table
    op.create_table(
        "sessions",
        sa.Column("session_id", sa.String(), nullable=False),
        sa.Column("date", sa.String(), nullable=False),
        sa.Column("subject", sa.String(), nullable=False),
        sa.PrimaryKeyConstraint("session_id", name="pk_sessions"),
    )

    # 4. attendance table
    op.create_table(
        "attendance",
        sa.Column("session_id", sa.String(), nullable=False),
        sa.Column("usn", sa.String(), nullable=False),
        sa.Column("room_id", sa.String(), nullable=False),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("source", sa.String(), nullable=False),
        sa.Column("confidence", sa.Float(), server_default="1.0", nullable=False),
        sa.CheckConstraint(
            "status IN ('PRESENT', 'ABSENT', 'PENDING', 'UNREVIEWED')",
            name="check_attendance_status",
        ),
        sa.ForeignKeyConstraint(
            ["session_id"],
            ["sessions.session_id"],
            name="fk_attendance_session_id",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["usn"],
            ["students.usn"],
            name="fk_attendance_usn",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["room_id"],
            ["rooms.room_id"],
            name="fk_attendance_room_id",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("session_id", "usn", name="pk_attendance"),
    )

    # Indexes on attendance
    op.create_index("idx_attendance_session", "attendance", ["session_id"], unique=False)
    op.create_index("idx_attendance_usn", "attendance", ["usn"], unique=False)
    op.create_index("idx_attendance_room", "attendance", ["room_id"], unique=False)


def downgrade() -> None:
    op.drop_index("idx_attendance_room", table_name="attendance")
    op.drop_index("idx_attendance_usn", table_name="attendance")
    op.drop_index("idx_attendance_session", table_name="attendance")
    op.drop_table("attendance")
    op.drop_table("sessions")
    op.drop_table("rooms")
    op.drop_table("students")

