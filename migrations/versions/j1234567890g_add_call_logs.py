"""add call_logs table

Revision ID: j1234567890g
Revises: i1234567890f
Create Date: 2026-01-25 07:20:00.000000
"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "j1234567890g"
down_revision = "i1234567890f"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "call_logs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("agent_id", sa.String(), nullable=False),
        sa.Column("timestamp", sa.DateTime(), nullable=False),
        sa.Column("text", sa.String(), nullable=True),
        sa.Column("status", sa.String(), nullable=True),
        sa.Column("raw_data", sa.JSON(), nullable=True),
    )
    op.create_index("ix_call_logs_agent_id", "call_logs", ["agent_id"], unique=False)


def downgrade():
    op.drop_index("ix_call_logs_agent_id", table_name="call_logs")
    op.drop_table("call_logs")
