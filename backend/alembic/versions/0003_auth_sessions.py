"""Create auth_sessions and auth_refresh_tokens tables for persistent sessions and rotation.

Revision ID: 0003_auth_sessions
Revises: 0002_rbac_tables
Create Date: 2026-11-10 07:50:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "0003_auth_sessions"
down_revision: Union[str, None] = "0002_rbac_tables"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. auth_sessions table
    op.create_table(
        "auth_sessions",
        sa.Column("session_id", sa.String(), nullable=False),
        sa.Column("user_id", sa.String(), nullable=False),
        sa.Column("created_at", sa.String(), nullable=False),
        sa.Column("absolute_expiry", sa.String(), nullable=False),
        sa.Column("revoked_at", sa.String(), nullable=True),
        sa.Column("remember_me", sa.Integer(), server_default="0", nullable=False),
        sa.Column("user_agent", sa.String(), nullable=True),
        sa.Column("ip_address", sa.String(), nullable=True),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.user_id"],
            name="fk_auth_sessions_user_id",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("session_id", name="pk_auth_sessions"),
    )
    op.create_index(
        "idx_auth_sessions_user_id",
        "auth_sessions",
        ["user_id", "revoked_at"],
    )
    op.create_index(
        "idx_auth_sessions_expiry",
        "auth_sessions",
        ["absolute_expiry"],
    )

    # 2. auth_refresh_tokens table
    op.create_table(
        "auth_refresh_tokens",
        sa.Column("token_id", sa.String(), nullable=False),
        sa.Column("session_id", sa.String(), nullable=False),
        sa.Column("token_hash", sa.String(length=64), nullable=False),
        sa.Column("rotation_seq", sa.Integer(), server_default="0", nullable=False),
        sa.Column("created_at", sa.String(), nullable=False),
        sa.Column("consumed_at", sa.String(), nullable=True),
        sa.Column("revoked_at", sa.String(), nullable=True),
        sa.ForeignKeyConstraint(
            ["session_id"],
            ["auth_sessions.session_id"],
            name="fk_auth_refresh_tokens_session_id",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("token_id", name="pk_auth_refresh_tokens"),
        sa.UniqueConstraint("token_hash", name="uq_auth_refresh_tokens_hash"),
    )
    op.create_index(
        "idx_auth_refresh_tokens_hash",
        "auth_refresh_tokens",
        ["token_hash"],
        unique=True,
    )
    op.create_index(
        "idx_auth_refresh_tokens_session",
        "auth_refresh_tokens",
        ["session_id"],
    )


def downgrade() -> None:
    op.drop_index("idx_auth_refresh_tokens_session", table_name="auth_refresh_tokens")
    op.drop_index("idx_auth_refresh_tokens_hash", table_name="auth_refresh_tokens")
    op.drop_table("auth_refresh_tokens")

    op.drop_index("idx_auth_sessions_expiry", table_name="auth_sessions")
    op.drop_index("idx_auth_sessions_user_id", table_name="auth_sessions")
    op.drop_table("auth_sessions")

