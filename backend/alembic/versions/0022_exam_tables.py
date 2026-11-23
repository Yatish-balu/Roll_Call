"""Add exams, room_assignments, and exam_seating tables for Form-B exam control system.

Revision ID: 0022_exam_tables
Revises: 0021_attendance_unlock_requests
"""

from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa


revision: str = "0022_exam_tables"
down_revision: Union[str, None] = "0021_attendance_unlock_requests"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    tables = set(insp.get_table_names())

    # 1. exams table
    if "exams" not in tables:
        op.create_table(
            "exams",
            sa.Column("exam_id", sa.String(50), primary_key=True, nullable=False),
            sa.Column("name", sa.String(200), nullable=False),
            sa.Column("exam_type", sa.String(30), nullable=False, server_default="THEORY_CIE"),
            sa.Column("semester", sa.Integer(), nullable=True),
            sa.Column("department", sa.String(100), nullable=True),
            sa.Column("date", sa.String(20), nullable=False),
            sa.Column("start_time", sa.String(20), nullable=False),
            sa.Column("end_time", sa.String(20), nullable=False),
            sa.Column("cutoff_minutes", sa.Integer(), nullable=False, server_default="45"),
            sa.Column("subject_code", sa.String(30), nullable=False),
            sa.Column("subject_name", sa.String(150), nullable=True),
            sa.Column("created_by", sa.String(50), nullable=True),
            sa.Column("created_at", sa.String(50), nullable=False),
        )
        op.create_index("ix_exams_date", "exams", ["date"])
        op.create_index("ix_exams_type", "exams", ["exam_type"])

    # 2. room_assignments table
    if "room_assignments" not in tables:
        op.create_table(
            "room_assignments",
            sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
            sa.Column("exam_id", sa.String(50), sa.ForeignKey("exams.exam_id", ondelete="CASCADE"), nullable=False),
            sa.Column("room_no", sa.String(50), nullable=False),
            sa.Column("block_name", sa.String(100), nullable=True),
            sa.Column("capacity", sa.Integer(), nullable=True),
            sa.Column("invigilator_id", sa.String(50), sa.ForeignKey("users.user_id", ondelete="SET NULL"), nullable=True),
            sa.Column("external_examiner_name", sa.String(150), nullable=True),
            sa.Column("external_examiner_college", sa.String(150), nullable=True),
            sa.Column("coordinator_id", sa.String(50), nullable=True),
            sa.Column("status", sa.String(30), nullable=False, server_default="SCHEDULED"),
            sa.Column("submitted_at", sa.String(50), nullable=True),
            sa.Column("submitted_by", sa.String(50), nullable=True),
        )
        op.create_index("ix_room_assignments_exam_room", "room_assignments", ["exam_id", "room_no"], unique=True)
        op.create_index("ix_room_assignments_invigilator", "room_assignments", ["invigilator_id"])

    # 3. exam_seating table
    if "exam_seating" not in tables:
        op.create_table(
            "exam_seating",
            sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
            sa.Column("exam_id", sa.String(50), sa.ForeignKey("exams.exam_id", ondelete="CASCADE"), nullable=False),
            sa.Column("room_no", sa.String(50), nullable=False),
            sa.Column("sl_no", sa.Integer(), nullable=False),
            sa.Column("usn", sa.String(30), nullable=False),
            sa.Column("name", sa.String(100), nullable=False),
            sa.Column("branch", sa.String(30), nullable=False),
            sa.Column("subject_code", sa.String(30), nullable=False),
            sa.Column("seat_no", sa.String(20), nullable=True),
            sa.Column("status", sa.String(20), nullable=False, server_default="ABSENT"),
            sa.Column("marked_by", sa.String(50), nullable=True),
            sa.Column("marked_source", sa.String(20), nullable=True),
            sa.Column("marked_at", sa.String(50), nullable=True),
        )
        op.create_index("ix_exam_seating_exam_usn", "exam_seating", ["exam_id", "usn"], unique=True)
        op.create_index("ix_exam_seating_exam_room", "exam_seating", ["exam_id", "room_no"])
        op.create_index("ix_exam_seating_branch", "exam_seating", ["branch"])


def downgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    tables = set(insp.get_table_names())

    if "exam_seating" in tables:
        op.drop_table("exam_seating")
    if "room_assignments" in tables:
        op.drop_table("room_assignments")
    if "exams" in tables:
        op.drop_table("exams")
