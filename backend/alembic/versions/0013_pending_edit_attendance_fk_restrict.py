"""PendingEdit.attendance_id: ON DELETE CASCADE -> RESTRICT.

Deleting an attendance row must never silently discard a staged (pending) edit
that the user has not yet confirmed or discarded. The application now rejects
such deletes with a clear 409/ValueError instead.

Revision ID: 0013_pending_edit_fk_restrict
Revises: 0012_students_academic_fks
Create Date: 2026-11-10 18:20:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "0013_pending_edit_fk_restrict"
down_revision: Union[str, None] = "0012_students_academic_fks"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

FK_NAME = "fk_pending_edits_attendance_id"


def _attendance_fk():
    """Return the current FK dict for pending_edits.attendance_id, if any."""
    inspector = sa.inspect(op.get_bind())
    for fk in inspector.get_foreign_keys("pending_edits"):
        if fk.get("constrained_columns") == ["attendance_id"]:
            return fk
    return None


def _swap(ondelete: str) -> None:
    """Recreate the attendance_id FK with the requested ON DELETE action."""
    current = _attendance_fk()
    if current is not None and (current.get("options") or {}).get("ondelete", "").upper() == ondelete:
        return  # already correct: idempotent

    name = (current or {}).get("name") or FK_NAME
    if op.get_bind().dialect.name == "sqlite":
        with op.batch_alter_table("pending_edits") as batch_op:
            batch_op.drop_constraint(name, type_="foreignkey")
            batch_op.create_foreign_key(
                FK_NAME,
                "attendance",
                ["attendance_id"],
                ["attendance_id"],
                ondelete=ondelete,
            )
    else:
        op.drop_constraint(name, table_name="pending_edits", type_="foreignkey")
        op.create_foreign_key(
            FK_NAME,
            "pending_edits",
            "attendance",
            ["attendance_id"],
            ["attendance_id"],
            ondelete=ondelete,
        )


def upgrade() -> None:
    _swap("RESTRICT")


def downgrade() -> None:
    _swap("CASCADE")
