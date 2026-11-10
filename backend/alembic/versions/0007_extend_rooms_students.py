"""Extend rooms and students with academic structure fields.

Revision ID: 0007_extend_rooms_students
Revises: 0006_faculty_staff
Create Date: 2026-11-10 10:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "0007_extend_rooms_students"
down_revision: Union[str, None] = "0006_faculty_staff"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Extend rooms table with new columns (no FK constraints - enforced at app level)
    op.add_column(
        "rooms",
        sa.Column("dept_id", sa.String(), nullable=True),
    )
    op.add_column(
        "rooms",
        sa.Column("room_type", sa.String(), nullable=True),
    )
    op.add_column(
        "rooms",
        sa.Column("capacity", sa.Integer(), nullable=True),
    )
    op.create_index("idx_rooms_dept_id", "rooms", ["dept_id"], unique=False)

    # Extend students table with new columns (no FK constraints - enforced at app level)
    op.add_column(
        "students",
        sa.Column("dept_id", sa.String(), nullable=True),
    )
    op.add_column(
        "students",
        sa.Column("semester_id", sa.String(), nullable=True),
    )
    op.add_column(
        "students",
        sa.Column("section_id", sa.String(), nullable=True),
    )
    op.add_column(
        "students",
        sa.Column("roll_no", sa.String(), nullable=True),
    )
    op.add_column(
        "students",
        sa.Column("batch_id", sa.String(), nullable=True),
    )
    op.create_index("idx_students_dept_id", "students", ["dept_id"], unique=False)
    op.create_index("idx_students_semester_id", "students", ["semester_id"], unique=False)
    op.create_index("idx_students_section_id", "students", ["section_id"], unique=False)
    op.create_index("idx_students_batch_id", "students", ["batch_id"], unique=False)


def downgrade() -> None:
    op.drop_index("idx_students_batch_id", table_name="students")
    op.drop_index("idx_students_section_id", table_name="students")
    op.drop_index("idx_students_semester_id", table_name="students")
    op.drop_index("idx_students_dept_id", table_name="students")
    op.drop_column("students", "batch_id")
    op.drop_column("students", "roll_no")
    op.drop_column("students", "section_id")
    op.drop_column("students", "semester_id")
    op.drop_column("students", "dept_id")

    op.drop_index("idx_rooms_dept_id", table_name="rooms")
    op.drop_column("rooms", "capacity")
    op.drop_column("rooms", "room_type")
    op.drop_column("rooms", "dept_id")
