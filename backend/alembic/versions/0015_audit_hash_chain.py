"""Add the audit hash chain and the security decoy table.

The audit log gains three nullable columns (``chain_id``, ``prev_hash``,
``row_hash``) so that every record can be linked to its predecessor with an
HMAC-SHA256 hash. A single-row ``audit_chain_head`` table holds the current
tip of each chain.

The columns stay nullable on purpose: records written before the chain was
activated keep working and are reported as *unverified* by the verification
command - they are never claimed to be cryptographically verified.

The HMAC secret is NOT part of this migration. It is provisioned separately by
the database owner through the environment (``AUDIT_CHAIN_HMAC_SECRET``).

Revision ID: 0015_audit_hash_chain
Revises: 0014_audit_actor_role
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0015_audit_hash_chain"
down_revision: Union[str, None] = "0014_audit_actor_role"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _sqlite_dialect() -> bool:
    return op.get_bind().dialect.name == "sqlite"


def upgrade() -> None:
    op.add_column("audit_log", sa.Column("chain_id", sa.String(), nullable=True))
    op.add_column("audit_log", sa.Column("prev_hash", sa.String(), nullable=True))
    op.add_column("audit_log", sa.Column("row_hash", sa.String(), nullable=True))
    op.create_index("idx_audit_log_chain", "audit_log", ["chain_id", "log_id"], unique=False)

    op.create_table(
        "audit_chain_head",
        sa.Column("chain_id", sa.String(), nullable=False),
        sa.Column("last_hash", sa.String(), nullable=True),
        sa.Column("last_log_id", sa.Integer(), nullable=True),
        sa.Column("updated_at", sa.String(), nullable=True),
        sa.PrimaryKeyConstraint("chain_id", name="pk_audit_chain_head"),
    )

    # Decoy (honeypot) records live in their own table: they are never mixed
    # with real student, attendance or session data.
    op.create_table(
        "security_decoys",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("decoy_kind", sa.String(), nullable=False),
        sa.Column("decoy_value", sa.String(), nullable=False),
        sa.Column("enabled", sa.Integer(), server_default="1", nullable=False),
        sa.Column("note", sa.String(), nullable=True),
        sa.Column("created_by", sa.String(), nullable=True),
        sa.Column("created_at", sa.String(), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_security_decoys"),
    )
    op.create_index("idx_security_decoys_value", "security_decoys", ["decoy_value"], unique=False)

    # The chain head must never be deleted: a missing head breaks the anchor.
    if _sqlite_dialect():
        op.execute(
            "CREATE TRIGGER IF NOT EXISTS trg_audit_chain_head_no_delete "
            "BEFORE DELETE ON audit_chain_head BEGIN "
            "SELECT RAISE(ABORT, 'audit_chain_head is append-only: deletions forbidden'); END"
        )
    else:
        op.execute(
            "CREATE OR REPLACE FUNCTION reject_audit_chain_head_delete() RETURNS TRIGGER AS $$ "
            "BEGIN RAISE EXCEPTION 'audit_chain_head is append-only: deletions forbidden'; "
            "END; $$ LANGUAGE plpgsql"
        )
        op.execute(
            "DROP TRIGGER IF EXISTS trg_audit_chain_head_no_delete ON audit_chain_head"
        )
        op.execute(
            "CREATE TRIGGER trg_audit_chain_head_no_delete BEFORE DELETE ON audit_chain_head "
            "FOR EACH ROW EXECUTE FUNCTION reject_audit_chain_head_delete()"
        )


def downgrade() -> None:
    op.drop_index("idx_security_decoys_value", table_name="security_decoys")
    op.drop_table("security_decoys")

    if _sqlite_dialect():
        op.execute("DROP TRIGGER IF EXISTS trg_audit_chain_head_no_delete")
    else:
        op.execute("DROP TRIGGER IF EXISTS trg_audit_chain_head_no_delete ON audit_chain_head")
        op.execute("DROP FUNCTION IF EXISTS reject_audit_chain_head_delete()")
    op.drop_table("audit_chain_head")

    op.drop_index("idx_audit_log_chain", table_name="audit_log")
    with op.batch_alter_table("audit_log") as batch_op:
        batch_op.drop_column("row_hash")
        batch_op.drop_column("prev_hash")
        batch_op.drop_column("chain_id")

    # The batch rebuild above recreates the table, so the append-only triggers
    # of migration 0002 have to be restored.
    if _sqlite_dialect():
        op.execute(
            "CREATE TRIGGER IF NOT EXISTS trg_audit_log_no_update "
            "BEFORE UPDATE ON audit_log BEGIN "
            "SELECT RAISE(ABORT, 'audit_log is append-only: updates forbidden'); END"
        )
        op.execute(
            "CREATE TRIGGER IF NOT EXISTS trg_audit_log_no_delete "
            "BEFORE DELETE ON audit_log BEGIN "
            "SELECT RAISE(ABORT, 'audit_log is append-only: deletions forbidden'); END"
        )
    else:
        op.execute(
            "CREATE OR REPLACE FUNCTION reject_audit_modification() RETURNS TRIGGER AS $$ "
            "BEGIN RAISE EXCEPTION 'audit_log is append-only: updates and deletions forbidden'; "
            "END; $$ LANGUAGE plpgsql"
        )
        op.execute("DROP TRIGGER IF EXISTS trg_audit_log_no_update ON audit_log")
        op.execute(
            "CREATE TRIGGER trg_audit_log_no_update BEFORE UPDATE ON audit_log "
            "FOR EACH ROW EXECUTE FUNCTION reject_audit_modification()"
        )
        op.execute("DROP TRIGGER IF EXISTS trg_audit_log_no_delete ON audit_log")
        op.execute(
            "CREATE TRIGGER trg_audit_log_no_delete BEFORE DELETE ON audit_log "
            "FOR EACH ROW EXECUTE FUNCTION reject_audit_modification()"
        )
