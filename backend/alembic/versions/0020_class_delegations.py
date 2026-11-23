"""Add class_delegations table for faculty class handovers and proxy substitutions.

Revision ID: 0020_class_delegations
Revises: 0019_chat_history
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0020_class_delegations"
down_revision: Union[str, None] = "0019_chat_history"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    tables = set(insp.get_table_names())

    if "class_delegations" not in tables:
        op.create_table(
            "class_delegations",
            sa.Column("delegation_id", sa.String(), primary_key=True, nullable=False),
            sa.Column(
                "session_id",
                sa.String(),
                sa.ForeignKey("sessions.session_id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column(
                "original_faculty_id",
                sa.String(),
                sa.ForeignKey("users.user_id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column(
                "substitute_faculty_id",
                sa.String(),
                sa.ForeignKey("users.user_id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column("delegation_date", sa.String(), nullable=False),
            sa.Column(
                "delegation_type",
                sa.String(),
                nullable=False,
                server_default="PROXY",
            ),
            sa.Column(
                "exchange_session_id",
                sa.String(),
                sa.ForeignKey("sessions.session_id", ondelete="SET NULL"),
                nullable=True,
            ),
            sa.Column("reason", sa.String(), nullable=True),
            sa.Column(
                "status",
                sa.String(),
                nullable=False,
                server_default="ACTIVE",
            ),
            sa.Column("created_at", sa.String(), nullable=False),
            sa.Column("updated_at", sa.String(), nullable=False),
        )
        op.create_index(
            "idx_class_delegations_session_id",
            "class_delegations",
            ["session_id"],
            unique=False,
        )
        op.create_index(
            "idx_class_delegations_orig_faculty",
            "class_delegations",
            ["original_faculty_id"],
            unique=False,
        )
        op.create_index(
            "idx_class_delegations_sub_faculty",
            "class_delegations",
            ["substitute_faculty_id"],
            unique=False,
        )
        op.create_index(
            "idx_class_delegations_date",
            "class_delegations",
            ["delegation_date"],
            unique=False,
        )


def downgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    tables = set(insp.get_table_names())

    if "class_delegations" in tables:
        op.drop_index("idx_class_delegations_date", table_name="class_delegations")
        op.drop_index(
            "idx_class_delegations_sub_faculty", table_name="class_delegations"
        )
        op.drop_index(
            "idx_class_delegations_orig_faculty", table_name="class_delegations"
        )
        op.drop_index(
            "idx_class_delegations_session_id", table_name="class_delegations"
        )
        op.drop_table("class_delegations")

