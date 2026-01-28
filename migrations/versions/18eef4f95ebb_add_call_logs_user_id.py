"""add user_id to call_logs

Revision ID: 18eef4f95ebb
Revises: j1234567890g
Create Date: 2026-01-28 09:30:00.000000
"""

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "18eef4f95ebb"
down_revision = "j1234567890g"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("call_logs", sa.Column("user_id", sa.Integer(), nullable=True))

    op.execute(
        """
        UPDATE call_logs
        SET user_id = (
            SELECT ar.user_id
            FROM agent_routing ar
            WHERE ar.agent_id = call_logs.agent_id
              AND ar.is_active = TRUE
              AND ar.status = 'active'
            ORDER BY ar.id DESC
            LIMIT 1
        )
        WHERE user_id IS NULL
        """
    )

    op.create_index("ix_call_logs_user_id", "call_logs", ["user_id"], unique=False)
    op.create_foreign_key(
        "fk_call_logs_user_id_users",
        "call_logs",
        "users",
        ["user_id"],
        ["id"],
    )


def downgrade():
    op.drop_constraint("fk_call_logs_user_id_users", "call_logs", type_="foreignkey")
    op.drop_index("ix_call_logs_user_id", table_name="call_logs")
    op.drop_column("call_logs", "user_id")
