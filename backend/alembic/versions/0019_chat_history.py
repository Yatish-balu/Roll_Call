"""Add user chat threads and messages tables for chat persistence and isolation.

Revision ID: 0019_chat_history
Revises: 0018_academic_events
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0019_chat_history"
down_revision: Union[str, None] = "0018_academic_events"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    tables = set(insp.get_table_names())

    if "user_chat_threads" not in tables:
        op.create_table(
            "user_chat_threads",
            sa.Column("thread_id", sa.String(), primary_key=True, nullable=False),
            sa.Column("user_id", sa.String(), sa.ForeignKey("users.user_id", ondelete="CASCADE"), nullable=False),
            sa.Column("title", sa.String(), nullable=False, server_default="New Conversation"),
            sa.Column("created_at", sa.String(), nullable=False),
            sa.Column("updated_at", sa.String(), nullable=False),
            sa.Column("is_pinned", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("is_archived", sa.Integer(), nullable=False, server_default="0"),
        )
        op.create_index("idx_user_chat_threads_user_id", "user_chat_threads", ["user_id"], unique=False)
        op.create_index("idx_user_chat_threads_updated_at", "user_chat_threads", ["updated_at"], unique=False)

    if "user_chat_messages" not in tables:
        op.create_table(
            "user_chat_messages",
            sa.Column("message_id", sa.String(), primary_key=True, nullable=False),
            sa.Column("thread_id", sa.String(), sa.ForeignKey("user_chat_threads.thread_id", ondelete="CASCADE"), nullable=False),
            sa.Column("user_id", sa.String(), sa.ForeignKey("users.user_id", ondelete="CASCADE"), nullable=False),
            sa.Column("sender", sa.String(), nullable=False),
            sa.Column("text", sa.String(), nullable=False),
            sa.Column("timestamp", sa.String(), nullable=False),
            sa.Column("metadata_json", sa.Text(), nullable=True),
            sa.Column("created_at", sa.String(), nullable=False),
        )
        op.create_index("idx_user_chat_messages_thread_id", "user_chat_messages", ["thread_id"], unique=False)
        op.create_index("idx_user_chat_messages_user_id", "user_chat_messages", ["user_id"], unique=False)
        op.create_index("idx_user_chat_messages_created_at", "user_chat_messages", ["created_at"], unique=False)


def downgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    tables = set(insp.get_table_names())

    if "user_chat_messages" in tables:
        op.drop_index("idx_user_chat_messages_created_at", table_name="user_chat_messages")
        op.drop_index("idx_user_chat_messages_user_id", table_name="user_chat_messages")
        op.drop_index("idx_user_chat_messages_thread_id", table_name="user_chat_messages")
        op.drop_table("user_chat_messages")

    if "user_chat_threads" in tables:
        op.drop_index("idx_user_chat_threads_updated_at", table_name="user_chat_threads")
        op.drop_index("idx_user_chat_threads_user_id", table_name="user_chat_threads")
        op.drop_table("user_chat_threads")
