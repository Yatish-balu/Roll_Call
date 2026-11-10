"""Add RBAC and audit tables, extend sessions with teacher references and backfill.

Revision ID: 0002_rbac_tables
Revises: 0001_initial_schema
Create Date: 2026-11-10 06:40:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "0002_rbac_tables"
down_revision: Union[str, None] = "0001_initial_schema"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    dialect = bind.dialect.name

    # 1. users table
    op.create_table(
        "users",
        sa.Column("user_id", sa.String(), nullable=False),
        sa.Column("email", sa.String(), nullable=False),
        sa.Column("role", sa.String(), nullable=False),
        sa.Column("hashed_password", sa.String(), nullable=True),
        sa.Column("is_active", sa.Integer(), server_default="1", nullable=False),
        sa.Column("created_at", sa.String(), nullable=False),
        sa.PrimaryKeyConstraint("user_id", name="pk_users"),
        sa.UniqueConstraint("email", name="uq_users_email"),
    )

    # 2. teacher_subjects table
    op.create_table(
        "teacher_subjects",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("user_id", sa.String(), nullable=False),
        sa.Column("subject_code", sa.String(), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.user_id"], ondelete="CASCADE", name="fk_teacher_subjects_user"),
        sa.PrimaryKeyConstraint("id", name="pk_teacher_subjects"),
        sa.UniqueConstraint("user_id", "subject_code", name="uq_teacher_subject"),
    )

    # 3. audit_log table
    op.create_table(
        "audit_log",
        sa.Column("log_id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("actor_id", sa.String(), nullable=False),
        sa.Column("action", sa.String(), nullable=False),
        sa.Column("session_id", sa.String(), nullable=True),
        sa.Column("usn", sa.String(), nullable=True),
        sa.Column("entity_type", sa.String(), nullable=False),
        sa.Column("entity_id", sa.String(), nullable=False),
        sa.Column("old_value", sa.String(), nullable=True),
        sa.Column("new_value", sa.String(), nullable=True),
        sa.Column("reason", sa.String(), nullable=True),
        sa.Column("timestamp", sa.String(), nullable=False),
        sa.ForeignKeyConstraint(["actor_id"], ["users.user_id"], ondelete="RESTRICT", name="fk_audit_log_actor"),
        sa.PrimaryKeyConstraint("log_id", name="pk_audit_log"),
    )
    op.create_index("idx_audit_log_actor_ts", "audit_log", ["actor_id", "timestamp"], unique=False)

    # 4. login_attempts table
    op.create_table(
        "login_attempts",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("user_id", sa.String(), nullable=True),
        sa.Column("ip_address", sa.String(), nullable=True),
        sa.Column("success", sa.Integer(), nullable=False),
        sa.Column("timestamp", sa.String(), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.user_id"], ondelete="SET NULL", name="fk_login_attempts_user"),
        sa.PrimaryKeyConstraint("id", name="pk_login_attempts"),
    )
    op.create_index("idx_login_attempts_user_ts", "login_attempts", ["user_id", "timestamp"], unique=False)

    # 5. pending_edits table
    op.create_table(
        "pending_edits",
        sa.Column("edit_id", sa.String(), nullable=False),
        sa.Column("user_id", sa.String(), nullable=False),
        sa.Column("session_id", sa.String(), nullable=False),
        sa.Column("usn", sa.String(), nullable=False),
        sa.Column("old_status", sa.String(), nullable=False),
        sa.Column("new_status", sa.String(), nullable=False),
        sa.Column("created_at", sa.String(), nullable=False),
        sa.Column("expires_at", sa.String(), nullable=False),
        sa.Column("consumed", sa.Integer(), server_default="0", nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.user_id"], ondelete="CASCADE", name="fk_pending_edits_user"),
        sa.ForeignKeyConstraint(
            ["session_id", "usn"],
            ["attendance.session_id", "attendance.usn"],
            ondelete="CASCADE",
            name="fk_pending_edits_attendance",
        ),
        sa.PrimaryKeyConstraint("edit_id", name="pk_pending_edits"),
    )
    op.create_index("idx_pending_edits_user_expiry", "pending_edits", ["user_id", "expires_at", "consumed"], unique=False)

    # 6. Insert legacy sentinel user BEFORE modifying sessions or foreign key validation
    op.execute(
        """
        INSERT INTO users (user_id, email, role, hashed_password, is_active, created_at)
        VALUES ('legacy', 'legacy@rollcall.internal', 'ADMIN', NULL, 0, '2026-10-24T00:00:00Z')
        """
    )

    # 7. Extend sessions table (Dialect-safe: direct ALTER TABLE on SQLite to avoid parent rebuild hazards)
    if dialect == "sqlite":
        op.execute("ALTER TABLE sessions ADD COLUMN created_at TEXT")
        op.execute("ALTER TABLE sessions ADD COLUMN teacher_id TEXT REFERENCES users(user_id) ON DELETE RESTRICT")
        op.execute("ALTER TABLE sessions ADD COLUMN subject_code TEXT")
    else:
        op.add_column("sessions", sa.Column("created_at", sa.String(), nullable=True))
        op.add_column("sessions", sa.Column("teacher_id", sa.String(), nullable=True))
        op.add_column("sessions", sa.Column("subject_code", sa.String(), nullable=True))
        op.create_foreign_key(
            "fk_sessions_teacher_id",
            "sessions",
            "users",
            ["teacher_id"],
            ["user_id"],
            ondelete="RESTRICT",
        )

    op.create_index("idx_sessions_teacher_created", "sessions", ["teacher_id", "created_at"], unique=False)

    # 8. Backfill historical sessions with explicit CASE mapping
    op.execute(
        """
        UPDATE sessions SET
          subject_code = CASE
            WHEN subject = 'Distributed Systems' THEN 'DIST-SYS'
            WHEN subject = 'Machine Learning'    THEN 'ML'
            WHEN subject = 'Computer Networks'   THEN 'CN'
            WHEN subject = 'Database Systems'    THEN 'DB-SYS'
            WHEN subject = 'Embedded Systems'    THEN 'ES'
            ELSE 'UNKNOWN'
          END,
          created_at = date || 'T00:00:00Z',
          teacher_id = 'legacy'
        WHERE teacher_id IS NULL
        """
    )

    # 9. Append-only triggers on audit_log
    if dialect == "sqlite":
        op.execute(
            """
            CREATE TRIGGER trg_audit_log_no_update
            BEFORE UPDATE ON audit_log
            BEGIN
                SELECT RAISE(ABORT, 'audit_log is append-only: updates forbidden');
            END;
            """
        )
        op.execute(
            """
            CREATE TRIGGER trg_audit_log_no_delete
            BEFORE DELETE ON audit_log
            BEGIN
                SELECT RAISE(ABORT, 'audit_log is append-only: deletions forbidden');
            END;
            """
        )
    else:
        op.execute(
            """
            CREATE OR REPLACE FUNCTION reject_audit_modification() RETURNS TRIGGER AS $$
            BEGIN
                RAISE EXCEPTION 'audit_log is append-only: updates and deletions forbidden';
            END;
            $$ LANGUAGE plpgsql;
            """
        )
        op.execute(
            """
            CREATE TRIGGER trg_audit_log_no_update
            BEFORE UPDATE ON audit_log
            FOR EACH ROW EXECUTE FUNCTION reject_audit_modification();
            """
        )
        op.execute(
            """
            CREATE TRIGGER trg_audit_log_no_delete
            BEFORE DELETE ON audit_log
            FOR EACH ROW EXECUTE FUNCTION reject_audit_modification();
            """
        )


def downgrade() -> None:
    bind = op.get_bind()
    dialect = bind.dialect.name

    # 1. Drop audit triggers
    if dialect == "sqlite":
        op.execute("DROP TRIGGER IF EXISTS trg_audit_log_no_delete")
        op.execute("DROP TRIGGER IF EXISTS trg_audit_log_no_update")
    else:
        op.execute("DROP TRIGGER IF EXISTS trg_audit_log_no_delete ON audit_log")
        op.execute("DROP TRIGGER IF EXISTS trg_audit_log_no_update ON audit_log")
        op.execute("DROP FUNCTION IF EXISTS reject_audit_modification")

    # 2. Drop indexes on sessions
    op.drop_index("idx_sessions_teacher_created", table_name="sessions")

    # 3. Drop sessions extended columns
    if dialect == "sqlite":
        with op.batch_alter_table("sessions") as batch_op:
            batch_op.drop_column("subject_code")
            batch_op.drop_column("teacher_id")
            batch_op.drop_column("created_at")
    else:
        op.drop_constraint("fk_sessions_teacher_id", "sessions", type_="foreignkey")
        op.drop_column("sessions", "subject_code")
        op.drop_column("sessions", "teacher_id")
        op.drop_column("sessions", "created_at")

    # 4. Drop new tables in reverse order
    op.drop_index("idx_pending_edits_user_expiry", table_name="pending_edits")
    op.drop_table("pending_edits")

    op.drop_index("idx_login_attempts_user_ts", table_name="login_attempts")
    op.drop_table("login_attempts")

    op.drop_index("idx_audit_log_actor_ts", table_name="audit_log")
    op.drop_table("audit_log")

    op.drop_table("teacher_subjects")
    op.drop_table("users")

