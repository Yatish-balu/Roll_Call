"""Consolidate duplicate teacher-subject mapping tables into faculty_subjects.

Migrates rows from public.teacher_subjects to public.faculty_subjects, adds
semester and UNIQUE(user_id, subject_code) constraint to faculty_subjects,
makes dept_id nullable for simple mappings, and drops public.teacher_subjects.

Revision ID: 0017_consolidate_subjects
Revises: 0016_account_security
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0017_consolidate_subjects"
down_revision: Union[str, None] = "0016_account_security"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _sqlite_dialect() -> bool:
    return op.get_bind().dialect.name == "sqlite"


def upgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    tables = set(insp.get_table_names())

    # 1. Ensure faculty_subjects table exists with proper structure
    if "faculty_subjects" not in tables:
        op.create_table(
            "faculty_subjects",
            sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True, nullable=False),
            sa.Column("user_id", sa.String(), nullable=False),
            sa.Column("subject_code", sa.String(), nullable=False),
            sa.Column("dept_id", sa.String(), nullable=True),
            sa.Column("semester", sa.Integer(), nullable=True),
            sa.ForeignKeyConstraint(["user_id"], ["users.user_id"], name="fk_faculty_subjects_user_id", ondelete="CASCADE"),
            sa.UniqueConstraint("user_id", "subject_code", name="uq_faculty_subject"),
        )
        op.create_index("idx_faculty_subjects_user_id", "faculty_subjects", ["user_id"], unique=False)
        op.create_index("idx_faculty_subjects_subject_code", "faculty_subjects", ["subject_code"], unique=False)
    else:
        # Table exists: check columns
        fs_cols = {c["name"] for c in insp.get_columns("faculty_subjects")}
        if "semester" not in fs_cols:
            op.add_column("faculty_subjects", sa.Column("semester", sa.Integer(), nullable=True))

        # In PostgreSQL, make dept_id nullable and relax FK if needed
        if not _sqlite_dialect():
            try:
                op.alter_column("faculty_subjects", "dept_id", nullable=True)
            except Exception:
                pass
            try:
                op.drop_constraint("fk_faculty_subjects_dept_id", "faculty_subjects", type_="foreignkey")
            except Exception:
                pass
            try:
                op.drop_constraint("fk_faculty_subjects_subject_code", "faculty_subjects", type_="foreignkey")
            except Exception:
                pass

        # Ensure UNIQUE(user_id, subject_code)
        uqs = {u["name"] for u in insp.get_unique_constraints("faculty_subjects")}
        if "uq_faculty_subject" not in uqs:
            try:
                op.create_unique_constraint("uq_faculty_subject", "faculty_subjects", ["user_id", "subject_code"])
            except Exception:
                pass

    # 2. Migrate existing rows from teacher_subjects to faculty_subjects
    if "teacher_subjects" in tables:
        try:
            rows = bind.execute(sa.text("SELECT user_id, subject_code FROM teacher_subjects")).fetchall()
            for uid, scode in rows:
                clean_uid = str(uid).strip()
                clean_scode = str(scode).strip().upper()
                exists = bind.execute(
                    sa.text("SELECT 1 FROM faculty_subjects WHERE user_id = :uid AND UPPER(subject_code) = :scode"),
                    {"uid": clean_uid, "scode": clean_scode},
                ).fetchone()
                if not exists:
                    bind.execute(
                        sa.text("INSERT INTO faculty_subjects (user_id, subject_code) VALUES (:uid, :scode)"),
                        {"uid": clean_uid, "scode": clean_scode},
                    )
        except Exception:
            pass

        # 3. Drop teacher_subjects
        op.drop_table("teacher_subjects")


def downgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    tables = set(insp.get_table_names())

    if "teacher_subjects" not in tables:
        op.create_table(
            "teacher_subjects",
            sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True, nullable=False),
            sa.Column("user_id", sa.String(), nullable=False),
            sa.Column("subject_code", sa.String(), nullable=False),
            sa.ForeignKeyConstraint(["user_id"], ["users.user_id"], ondelete="CASCADE"),
            sa.UniqueConstraint("user_id", "subject_code", name="uq_teacher_subject"),
        )
        if "faculty_subjects" in tables:
            try:
                rows = bind.execute(sa.text("SELECT user_id, subject_code FROM faculty_subjects")).fetchall()
                for uid, scode in rows:
                    bind.execute(
                        sa.text("INSERT INTO teacher_subjects (user_id, subject_code) VALUES (:uid, :scode)"),
                        {"uid": uid, "scode": scode},
                    )
            except Exception:
                pass
