"""Account security: password reset state, MFA state and shared rate limits.

Adds to ``users``:

* ``password_reset_token`` / ``password_reset_token_expires`` - only the
  SHA-256 hash of a reset token is stored, together with its expiry;
* ``mfa_secret`` - the AES-GCM encrypted TOTP secret (the encryption key
  lives in the environment, never in the database);
* ``mfa_enabled``, ``mfa_recovery_codes`` (salted hashes), ``mfa_last_counter``
  (TOTP replay protection).

Adds ``security_rate_limits`` - shared rate-limit counters so that the
protection is not process-local.

Revision ID: 0016_account_security
Revises: 0015_audit_hash_chain
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0016_account_security"
down_revision: Union[str, None] = "0015_audit_hash_chain"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    existing_cols = {col["name"] for col in insp.get_columns("users")}
    if "name" not in existing_cols:
        op.add_column("users", sa.Column("name", sa.String(), nullable=True))
    if "password_reset_token" not in existing_cols:
        op.add_column("users", sa.Column("password_reset_token", sa.String(), nullable=True))
    if "password_reset_token_expires" not in existing_cols:
        op.add_column("users", sa.Column("password_reset_token_expires", sa.String(), nullable=True))
    if "mfa_secret" not in existing_cols:
        op.add_column("users", sa.Column("mfa_secret", sa.String(), nullable=True))
    if "mfa_enabled" not in existing_cols:
        op.add_column(
            "users",
            sa.Column("mfa_enabled", sa.Integer(), server_default="0", nullable=False),
        )
    if "mfa_recovery_codes" not in existing_cols:
        op.add_column("users", sa.Column("mfa_recovery_codes", sa.String(), nullable=True))
    if "mfa_last_counter" not in existing_cols:
        op.add_column("users", sa.Column("mfa_last_counter", sa.Integer(), nullable=True))

    existing_tables = set(insp.get_table_names())
    if "security_rate_limits" not in existing_tables:
        op.create_table(
            "security_rate_limits",
            sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
            sa.Column("scope", sa.String(), nullable=False),
            sa.Column("key", sa.String(), nullable=False),
            sa.Column("attempts", sa.Integer(), server_default="0", nullable=False),
            sa.Column("window_started_at", sa.String(), nullable=True),
            sa.Column("blocked_until", sa.String(), nullable=True),
            sa.Column("updated_at", sa.String(), nullable=True),
            sa.PrimaryKeyConstraint("id", name="pk_security_rate_limits"),
            sa.UniqueConstraint("scope", "key", name="uq_security_rate_limits_scope_key"),
        )
        op.create_index(
            "idx_security_rate_limits_blocked",
            "security_rate_limits",
            ["blocked_until"],
            unique=False,
        )


def downgrade() -> None:
    op.drop_index("idx_security_rate_limits_blocked", table_name="security_rate_limits")
    op.drop_table("security_rate_limits")

    with op.batch_alter_table("users") as batch_op:
        batch_op.drop_column("mfa_last_counter")
        batch_op.drop_column("mfa_recovery_codes")
        batch_op.drop_column("mfa_enabled")
        batch_op.drop_column("mfa_secret")
        batch_op.drop_column("password_reset_token_expires")
        batch_op.drop_column("password_reset_token")
        batch_op.drop_column("name")
