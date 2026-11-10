"""Faculty-subject assignments and department staff tables.

Revision ID: 0006_faculty_staff
Revises: 0005_academic_structure
Create Date: 2026-11-10 10:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "0006_faculty_staff"
down_revision: Union[str, None] = "0005_academic_structure"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. faculty_subjects table
    op.create_table(
        "faculty_subjects",
        sa.Column("id", sa.Integer(), nullable=False, autoincrement=True),
        sa.Column("user_id", sa.String(), nullable=False),
        sa.Column("subject_code", sa.String(), nullable=False),
        sa.Column("dept_id", sa.String(), nullable=False),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.user_id"],
            name="fk_faculty_subjects_user_id",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["subject_code"],
            ["subjects.subject_code"],
            name="fk_faculty_subjects_subject_code",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["dept_id"],
            ["departments.dept_id"],
            name="fk_faculty_subjects_dept_id",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_faculty_subjects"),
        sa.UniqueConstraint(
            "user_id", "subject_code", "dept_id", name="uq_faculty_subject_dept"
        ),
    )
    op.create_index("idx_faculty_subjects_user_id", "faculty_subjects", ["user_id"], unique=False)
    op.create_index(
        "idx_faculty_subjects_subject_code", "faculty_subjects", ["subject_code"], unique=False
    )

    # 2. department_staff table
    op.create_table(
        "department_staff",
        sa.Column("id", sa.Integer(), nullable=False, autoincrement=True),
        sa.Column("user_id", sa.String(), nullable=False),
        sa.Column("dept_id", sa.String(), nullable=False),
        sa.Column("role_in_dept", sa.String(), nullable=False),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.user_id"],
            name="fk_department_staff_user_id",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["dept_id"],
            ["departments.dept_id"],
            name="fk_department_staff_dept_id",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_department_staff"),
        sa.UniqueConstraint("user_id", "dept_id", name="uq_department_staff"),
    )
    op.create_index("idx_department_staff_user_id", "department_staff", ["user_id"], unique=False)
    op.create_index(
        "idx_department_staff_dept_id", "department_staff", ["dept_id"], unique=False
    )


def downgrade() -> None:
    op.drop_index("idx_department_staff_dept_id", table_name="department_staff")
    op.drop_index("idx_department_staff_user_id", table_name="department_staff")
    op.drop_table("department_staff")
    op.drop_index("idx_faculty_subjects_subject_code", table_name="faculty_subjects")
    op.drop_index("idx_faculty_subjects_user_id", table_name="faculty_subjects")
    op.drop_table("faculty_subjects")
