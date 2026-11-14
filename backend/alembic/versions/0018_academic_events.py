"""Add institutional academic events table.

Revision ID: 0018_academic_events
Revises: 0017_consolidate_subjects
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0018_academic_events"
down_revision: Union[str, None] = "0017_consolidate_subjects"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    tables = set(insp.get_table_names())

    if "academic_events" not in tables:
        op.create_table(
            "academic_events",
            sa.Column("event_id", sa.String(), primary_key=True, nullable=False),
            sa.Column("title", sa.String(), nullable=False),
            sa.Column("event_date", sa.String(), nullable=False),
            sa.Column("end_date", sa.String(), nullable=True),
            sa.Column("event_type", sa.String(), nullable=False, server_default="ACADEMIC"),
            sa.Column("description", sa.String(), nullable=True),
            sa.Column("target_dept", sa.String(), nullable=True, server_default="ALL"),
            sa.Column("created_at", sa.String(), nullable=False),
        )
        op.create_index("idx_academic_events_date", "academic_events", ["event_date"], unique=False)
        op.create_index("idx_academic_events_type", "academic_events", ["event_type"], unique=False)


def downgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    tables = set(insp.get_table_names())

    if "academic_events" in tables:
        op.drop_index("idx_academic_events_type", table_name="academic_events")
        op.drop_index("idx_academic_events_date", table_name="academic_events")
        op.drop_table("academic_events")

