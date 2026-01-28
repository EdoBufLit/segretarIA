"""update usage_events call_id to call_logs FK

Revision ID: 20260128183530
Revises: 13559fef0d92
Create Date: 2026-01-28 18:35:30.000000
"""

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "20260128183530"
down_revision = "13559fef0d92"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("usage_events") as batch:
        batch.alter_column(
            "call_id",
            existing_type=sa.String(),
            type_=sa.Integer(),
            nullable=False,
        )
        batch.create_foreign_key(
            "fk_usage_events_call_id_call_logs",
            "call_logs",
            ["call_id"],
            ["id"],
        )


def downgrade():
    with op.batch_alter_table("usage_events") as batch:
        batch.drop_constraint("fk_usage_events_call_id_call_logs", type_="foreignkey")
        batch.alter_column(
            "call_id",
            existing_type=sa.Integer(),
            type_=sa.String(),
            nullable=True,
        )
