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
        fs_cols = {c["name"] for c in insp.get_columns("faculty_subjects")}
        uqs = {u["name"] for u in insp.get_unique_constraints("faculty_subjects")}
        fks = {fk["name"] for fk in insp.get_foreign_keys("faculty_subjects")}

        if _sqlite_dialect():
            with op.batch_alter_table("faculty_subjects") as batch_op:
                if "semester" not in fs_cols:
                    batch_op.add_column(sa.Column("semester", sa.Integer(), nullable=True))
                batch_op.alter_column("dept_id", existing_type=sa.String(), nullable=True)
                if "uq_faculty_subject_dept" in uqs:
                    batch_op.drop_constraint("uq_faculty_subject_dept", type_="unique")
                if "uq_faculty_subject" not in uqs:
                    batch_op.create_unique_constraint("uq_faculty_subject", ["user_id", "subject_code"])
                if "fk_faculty_subjects_subject_code" in fks:
                    batch_op.drop_constraint("fk_faculty_subjects_subject_code", type_="foreignkey")
                if "fk_faculty_subjects_dept_id" in fks:
                    batch_op.drop_constraint("fk_faculty_subjects_dept_id", type_="foreignkey")
        else:
            if "semester" not in fs_cols:
                op.add_column("faculty_subjects", sa.Column("semester", sa.Integer(), nullable=True))
            try:
                op.alter_column("faculty_subjects", "dept_id", nullable=True)
            except Exception:
                pass
            if "uq_faculty_subject_dept" in uqs:
                try:
                    op.drop_constraint("uq_faculty_subject_dept", "faculty_subjects", type_="unique")
                except Exception:
                    pass
            if "uq_faculty_subject" not in uqs:
                try:
                    op.create_unique_constraint("uq_faculty_subject", "faculty_subjects", ["user_id", "subject_code"])
                except Exception:
                    pass
            if "fk_faculty_subjects_subject_code" in fks:
                try:
                    op.drop_constraint("fk_faculty_subjects_subject_code", "faculty_subjects", type_="foreignkey")
                except Exception:
                    pass
            if "fk_faculty_subjects_dept_id" in fks:
                try:
                    op.drop_constraint("fk_faculty_subjects_dept_id", "faculty_subjects", type_="foreignkey")
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
