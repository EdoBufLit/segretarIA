"""add agent_settings table

Revision ID: i1234567890f
Revises: h1234567890e
Create Date: 2026-01-25 06:45:00.000000
"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "i1234567890f"
down_revision = "h1234567890e"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "agent_settings",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("agent_id", sa.String(), nullable=False),
        sa.Column("greeting", sa.String(), nullable=True),
        sa.Column("notes", sa.String(), nullable=True),
        sa.Column("agent_phone_number_id", sa.String(), nullable=True),
        sa.Column("test_phone_number", sa.String(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
    )
    op.create_index("ix_agent_settings_agent_id", "agent_settings", ["agent_id"], unique=True)


def downgrade():
    op.drop_index("ix_agent_settings_agent_id", table_name="agent_settings")
    op.drop_table("agent_settings")
