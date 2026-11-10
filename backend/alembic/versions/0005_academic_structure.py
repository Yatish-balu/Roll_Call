"""Academic structure tables: academic_years, semesters, sections, batches, subjects.

Revision ID: 0005_academic_structure
Revises: 0004_colleges_departments
Create Date: 2026-11-10 10:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "0005_academic_structure"
down_revision: Union[str, None] = "0004_colleges_departments"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. academic_years table
    op.create_table(
        "academic_years",
        sa.Column("year_id", sa.String(), nullable=False),
        sa.Column("college_id", sa.String(), nullable=False),
        sa.Column("year_label", sa.String(), nullable=False),
        sa.Column("start_date", sa.String(), nullable=False),
        sa.Column("end_date", sa.String(), nullable=False),
        sa.Column("is_active", sa.Integer(), nullable=False, server_default="1"),
        sa.ForeignKeyConstraint(
            ["college_id"],
            ["colleges.college_id"],
            name="fk_academic_years_college_id",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("year_id", name="pk_academic_years"),
        sa.UniqueConstraint("college_id", "year_label", name="uq_academic_year_college_label"),
    )
    op.create_index("idx_academic_years_college_id", "academic_years", ["college_id"], unique=False)

    # 2. semesters table
    op.create_table(
        "semesters",
        sa.Column("semester_id", sa.String(), nullable=False),
        sa.Column("year_id", sa.String(), nullable=False),
        sa.Column("semester_label", sa.String(), nullable=False),
        sa.Column("semester_number", sa.Integer(), nullable=False),
        sa.Column("start_date", sa.String(), nullable=False),
        sa.Column("end_date", sa.String(), nullable=False),
        sa.Column("is_active", sa.Integer(), nullable=False, server_default="1"),
        sa.ForeignKeyConstraint(
            ["year_id"],
            ["academic_years.year_id"],
            name="fk_semesters_year_id",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("semester_id", name="pk_semesters"),
        sa.UniqueConstraint("year_id", "semester_number", name="uq_semester_year_number"),
    )
    op.create_index("idx_semesters_year_id", "semesters", ["year_id"], unique=False)

    # 3. sections table
    op.create_table(
        "sections",
        sa.Column("section_id", sa.String(), nullable=False),
        sa.Column("dept_id", sa.String(), nullable=False),
        sa.Column("semester_id", sa.String(), nullable=False),
        sa.Column("section_label", sa.String(), nullable=False),
        sa.Column("batch_size", sa.Integer(), nullable=True),
        sa.ForeignKeyConstraint(
            ["dept_id"],
            ["departments.dept_id"],
            name="fk_sections_dept_id",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["semester_id"],
            ["semesters.semester_id"],
            name="fk_sections_semester_id",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("section_id", name="pk_sections"),
        sa.UniqueConstraint(
            "dept_id", "semester_id", "section_label", name="uq_section_dept_semester_label"
        ),
    )
    op.create_index("idx_sections_dept_id", "sections", ["dept_id"], unique=False)
    op.create_index("idx_sections_semester_id", "sections", ["semester_id"], unique=False)

    # 4. batches table
    op.create_table(
        "batches",
        sa.Column("batch_id", sa.String(), nullable=False),
        sa.Column("dept_id", sa.String(), nullable=False),
        sa.Column("semester_id", sa.String(), nullable=False),
        sa.Column("section_id", sa.String(), nullable=False),
        sa.Column("batch_label", sa.String(), nullable=False),
        sa.Column("batch_type", sa.String(), nullable=False),
        sa.ForeignKeyConstraint(
            ["dept_id"],
            ["departments.dept_id"],
            name="fk_batches_dept_id",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["semester_id"],
            ["semesters.semester_id"],
            name="fk_batches_semester_id",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["section_id"],
            ["sections.section_id"],
            name="fk_batches_section_id",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("batch_id", name="pk_batches"),
        sa.UniqueConstraint(
            "dept_id", "semester_id", "section_id", "batch_label",
            name="uq_batch_dept_semester_section_label",
        ),
    )
    op.create_index("idx_batches_dept_id", "batches", ["dept_id"], unique=False)
    op.create_index("idx_batches_section_id", "batches", ["section_id"], unique=False)

    # 5. subjects table
    op.create_table(
        "subjects",
        sa.Column("subject_code", sa.String(), nullable=False),
        sa.Column("dept_id", sa.String(), nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("credits", sa.Integer(), nullable=True),
        sa.Column("hours_per_week", sa.Integer(), nullable=True),
        sa.Column("subject_type", sa.String(), nullable=False),
        sa.ForeignKeyConstraint(
            ["dept_id"],
            ["departments.dept_id"],
            name="fk_subjects_dept_id",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("subject_code", name="pk_subjects"),
    )
    op.create_index("idx_subjects_dept_id", "subjects", ["dept_id"], unique=False)


def downgrade() -> None:
    op.drop_index("idx_subjects_dept_id", table_name="subjects")
    op.drop_table("subjects")
    op.drop_index("idx_batches_section_id", table_name="batches")
    op.drop_index("idx_batches_dept_id", table_name="batches")
    op.drop_table("batches")
    op.drop_index("idx_sections_semester_id", table_name="sections")
    op.drop_index("idx_sections_dept_id", table_name="sections")
    op.drop_table("sections")
    op.drop_index("idx_semesters_year_id", table_name="semesters")
    op.drop_table("semesters")
    op.drop_index("idx_academic_years_college_id", table_name="academic_years")
    op.drop_table("academic_years")
