"""Reconcile students academic FKs with the SQLAlchemy model.

Revision ID: 0012_students_academic_fks
Revises: 0011_pending_edit_attendance_id
Create Date: 2026-11-10 17:05:00.000000

Migration 0007 added students.dept_id / semester_id / section_id / batch_id as
plain columns and never created the foreign keys declared by the model. On a
migrated database those references were therefore unenforced (dangling ids were
accepted, and a department/semester delete silently orphaned students) while a
``create_all`` database enforced them - a genuine model/migration drift.

All four columns are nullable and empty in existing data, so adding the
constraints is non-destructive. Downgrade removes only the constraints.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "0012_students_academic_fks"
down_revision: Union[str, None] = "0011_pending_edit_attendance_id"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

STUDENT_FKS = (
    ("fk_students_dept_id", "dept_id", "departments", "dept_id"),
    ("fk_students_semester_id", "semester_id", "semesters", "semester_id"),
    ("fk_students_section_id", "section_id", "sections", "section_id"),
    ("fk_students_batch_id", "batch_id", "batches", "batch_id"),
)


def _is_sqlite() -> bool:
    return op.get_bind().dialect.name == "sqlite"


def _existing_fk_names(table: str) -> set[str]:
    inspector = sa.inspect(op.get_bind())
    return {fk["name"] for fk in inspector.get_foreign_keys(table) if fk.get("name")}


def upgrade() -> None:
    existing = _existing_fk_names("students")

    if _is_sqlite():
        with op.batch_alter_table("students") as batch_op:
            for name, column, ref_table, ref_column in STUDENT_FKS:
                if name in existing:
                    continue
                batch_op.create_foreign_key(
                    name, ref_table, [column], [ref_column], ondelete="RESTRICT"
                )
    else:
        for name, column, ref_table, ref_column in STUDENT_FKS:
            if name in existing:
                continue
            op.create_foreign_key(
                name, "students", ref_table, [column], [ref_column], ondelete="RESTRICT"
            )


def downgrade() -> None:
    existing = _existing_fk_names("students")

    if _is_sqlite():
        with op.batch_alter_table("students") as batch_op:
            for name, _column, _ref_table, _ref_column in STUDENT_FKS:
                if name in existing:
                    batch_op.drop_constraint(name, type_="foreignkey")
    else:
        for name, _column, _ref_table, _ref_column in STUDENT_FKS:
            if name in existing:
                op.drop_constraint(name, "students", type_="foreignkey")
