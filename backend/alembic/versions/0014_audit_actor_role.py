"""Add the actor role to the append-only audit log (N5).

Unlimited attendance editing requires every successful modification to record
who performed it, not only who they are. ``actor_role`` stores the role of the
actor at the moment of the action, taken from the verified authentication
context (never from a request payload, chat text or LLM output).

The column is nullable so that historical audit rows (written before N5) stay
valid and are not rewritten - the audit log is append-only.

Revision ID: 0014_audit_actor_role
Revises: 0013_pending_edit_fk_restrict
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0014_audit_actor_role"
down_revision: Union[str, None] = "0013_pending_edit_fk_restrict"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("audit_log", sa.Column("actor_role", sa.String(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("audit_log") as batch_op:
        batch_op.drop_column("actor_role")
