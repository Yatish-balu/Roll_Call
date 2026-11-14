"""Add attendance_unlock_requests table for teacher permission requests on locked sessions (>24h).

Revision ID: 0021_attendance_unlock_requests
Revises: 0020_class_delegations
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0021_attendance_unlock_requests"
down_revision: Union[str, None] = "0020_class_delegations"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    tables = set(insp.get_table_names())

    if "attendance_unlock_requests" not in tables:
        op.create_table(
            "attendance_unlock_requests",
            sa.Column("request_id", sa.String(50), primary_key=True, nullable=False),
            sa.Column(
                "session_id",
                sa.String(50),
                sa.ForeignKey("sessions.session_id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column(
                "teacher_id",
                sa.String(64),
                sa.ForeignKey("users.user_id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column("reason", sa.Text(), nullable=False),
            sa.Column("target_usns", sa.Text(), nullable=True),
            sa.Column("requested_change", sa.String(100), nullable=True),
            sa.Column("status", sa.String(20), nullable=False, server_default="PENDING"),
            sa.Column("admin_notes", sa.Text(), nullable=True),
            sa.Column(
                "reviewed_by",
                sa.String(64),
                sa.ForeignKey("users.user_id", ondelete="SET NULL"),
                nullable=True,
            ),
            sa.Column("reviewed_at", sa.String(50), nullable=True),
            sa.Column("created_at", sa.String(50), nullable=False),
            sa.Column("expires_at", sa.String(50), nullable=True),
        )
        op.create_index(
            "ix_attendance_unlock_requests_session_teacher",
            "attendance_unlock_requests",
            ["session_id", "teacher_id"],
        )
        op.create_index(
            "ix_attendance_unlock_requests_status",
            "attendance_unlock_requests",
            ["status"],
        )


def downgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    tables = set(insp.get_table_names())

    if "attendance_unlock_requests" in tables:
        op.drop_index(
            "ix_attendance_unlock_requests_status",
            table_name="attendance_unlock_requests",
        )
        op.drop_index(
            "ix_attendance_unlock_requests_session_teacher",
            table_name="attendance_unlock_requests",
        )
        op.drop_table("attendance_unlock_requests")
