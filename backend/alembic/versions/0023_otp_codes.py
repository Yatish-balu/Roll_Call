"""add otp_codes table

Revision ID: 0023_otp_codes
Revises: 0022_exam_tables
Create Date: 2026-11-24 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa

revision = "0023_otp_codes"
down_revision = "0022_exam_tables"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "otp_codes",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.String(), nullable=False),
        sa.Column("code", sa.String(length=6), nullable=False),
        sa.Column("expires_at", sa.DateTime(), nullable=False),
        sa.Column("used", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id", name="uq_otp_user"),
    )
    op.create_index("ix_otp_expires", "otp_codes", ["expires_at"])


def downgrade() -> None:
    op.drop_index("ix_otp_expires", table_name="otp_codes")
    op.drop_table("otp_codes")