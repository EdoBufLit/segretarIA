"""add call_log_id to usage_events

Revision ID: 20260128185824
Revises: 13559fef0d92
Create Date: 2026-01-28 18:58:24.000000
"""

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "20260128185824"
down_revision = "13559fef0d92"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("usage_events") as batch:
        batch.add_column(sa.Column("call_log_id", sa.Integer(), nullable=True))
        batch.create_foreign_key(
            "fk_usage_events_call_log_id_call_logs",
            "call_logs",
            ["call_log_id"],
            ["id"],
        )
        batch.create_index("ix_usage_events_call_log_id", ["call_log_id"], unique=False)
        batch.create_unique_constraint("uq_usage_events_call_log_id", ["call_log_id"])

    op.execute(
        """
        UPDATE usage_events
        SET call_log_id = call_id::int
        WHERE call_id ~ '^[0-9]+$'
          AND call_log_id IS NULL
        """
    )


def downgrade():
    with op.batch_alter_table("usage_events") as batch:
        batch.drop_constraint("uq_usage_events_call_log_id", type_="unique")
        batch.drop_index("ix_usage_events_call_log_id")
        batch.drop_constraint("fk_usage_events_call_log_id_call_logs", type_="foreignkey")
        batch.drop_column("call_log_id")
