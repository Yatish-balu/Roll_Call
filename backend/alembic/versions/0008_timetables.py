"""Timetables and timetable entries tables.

Revision ID: 0008_timetables
Revises: 0007_extend_rooms_students
Create Date: 2026-11-10 10:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "0008_timetables"
down_revision: Union[str, None] = "0007_extend_rooms_students"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. timetables table
    op.create_table(
        "timetables",
        sa.Column("timetable_id", sa.String(), nullable=False),
        sa.Column("dept_id", sa.String(), nullable=False),
        sa.Column("semester_id", sa.String(), nullable=False),
        sa.Column("section_id", sa.String(), nullable=False),
        sa.Column("year_id", sa.String(), nullable=False),
        sa.Column("effective_from", sa.String(), nullable=False),
        sa.Column("effective_to", sa.String(), nullable=True),
        sa.Column("revision_number", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("is_active", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("created_at", sa.String(), nullable=False),
        sa.ForeignKeyConstraint(
            ["dept_id"],
            ["departments.dept_id"],
            name="fk_timetables_dept_id",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["semester_id"],
            ["semesters.semester_id"],
            name="fk_timetables_semester_id",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["section_id"],
            ["sections.section_id"],
            name="fk_timetables_section_id",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["year_id"],
            ["academic_years.year_id"],
            name="fk_timetables_year_id",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("timetable_id", name="pk_timetables"),
        sa.UniqueConstraint(
            "dept_id", "semester_id", "section_id", "year_id",
            name="uq_timetable_dept_semester_section_year",
        ),
    )
    op.create_index("idx_timetables_dept_id", "timetables", ["dept_id"], unique=False)
    op.create_index("idx_timetables_is_active", "timetables", ["is_active"], unique=False)

    # 2. timetable_entries table
    op.create_table(
        "timetable_entries",
        sa.Column("entry_id", sa.String(), nullable=False),
        sa.Column("timetable_id", sa.String(), nullable=False),
        sa.Column("day_of_week", sa.String(), nullable=False),
        sa.Column("period_number", sa.Integer(), nullable=False),
        sa.Column("start_time", sa.String(), nullable=False),
        sa.Column("end_time", sa.String(), nullable=False),
        sa.Column("subject_code", sa.String(), nullable=False),
        sa.Column("room_id", sa.String(), nullable=False),
        sa.Column("faculty_id", sa.String(), nullable=True),
        sa.Column("batch_id", sa.String(), nullable=True),
        sa.Column("duration_minutes", sa.Integer(), nullable=True),
        sa.ForeignKeyConstraint(
            ["timetable_id"],
            ["timetables.timetable_id"],
            name="fk_timetable_entries_timetable_id",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["subject_code"],
            ["subjects.subject_code"],
            name="fk_timetable_entries_subject_code",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["room_id"],
            ["rooms.room_id"],
            name="fk_timetable_entries_room_id",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["faculty_id"],
            ["users.user_id"],
            name="fk_timetable_entries_faculty_id",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["batch_id"],
            ["batches.batch_id"],
            name="fk_timetable_entries_batch_id",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("entry_id", name="pk_timetable_entries"),
    )
    op.create_index("idx_timetable_entries_timetable_id", "timetable_entries", ["timetable_id"], unique=False)
    op.create_index("idx_timetable_entries_day_of_week", "timetable_entries", ["day_of_week"], unique=False)
    op.create_index("idx_timetable_entries_room_id", "timetable_entries", ["room_id"], unique=False)
    op.create_index("idx_timetable_entries_faculty_id", "timetable_entries", ["faculty_id"], unique=False)
    op.create_index("idx_timetable_entries_batch_id", "timetable_entries", ["batch_id"], unique=False)


def downgrade() -> None:
    op.drop_index("idx_timetable_entries_batch_id", table_name="timetable_entries")
    op.drop_index("idx_timetable_entries_faculty_id", table_name="timetable_entries")
    op.drop_index("idx_timetable_entries_room_id", table_name="timetable_entries")
    op.drop_index("idx_timetable_entries_day_of_week", table_name="timetable_entries")
    op.drop_index("idx_timetable_entries_timetable_id", table_name="timetable_entries")
    op.drop_table("timetable_entries")
    op.drop_index("idx_timetables_is_active", table_name="timetables")
    op.drop_index("idx_timetables_dept_id", table_name="timetables")
    op.drop_table("timetables")
