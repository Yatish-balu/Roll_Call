"""Colleges and departments tables.

Revision ID: 0004_colleges_departments
Revises: 0003_auth_sessions
Create Date: 2026-11-10 10:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "0004_colleges_departments"
down_revision: Union[str, None] = "0003_auth_sessions"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. colleges table
    op.create_table(
        "colleges",
        sa.Column("college_id", sa.String(), nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("code", sa.String(), nullable=False),
        sa.Column("address", sa.String(), nullable=True),
        sa.Column("created_at", sa.String(), nullable=False),
        sa.PrimaryKeyConstraint("college_id", name="pk_colleges"),
        sa.UniqueConstraint("code", name="uq_colleges_code"),
    )

    # 2. departments table
    op.create_table(
        "departments",
        sa.Column("dept_id", sa.String(), nullable=False),
        sa.Column("college_id", sa.String(), nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("code", sa.String(), nullable=False),
        sa.Column("head_of_dept_id", sa.String(), nullable=True),
        sa.Column("created_at", sa.String(), nullable=False),
        sa.ForeignKeyConstraint(
            ["college_id"],
            ["colleges.college_id"],
            name="fk_departments_college_id",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["head_of_dept_id"],
            ["users.user_id"],
            name="fk_departments_head_of_dept_id",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("dept_id", name="pk_departments"),
        sa.UniqueConstraint("college_id", "code", name="uq_department_college_code"),
    )
    op.create_index("idx_departments_college_id", "departments", ["college_id"], unique=False)


def downgrade() -> None:
    op.drop_index("idx_departments_college_id", table_name="departments")
    op.drop_table("departments")
    op.drop_table("colleges")
