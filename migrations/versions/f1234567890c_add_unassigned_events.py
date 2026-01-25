"""Add unassigned_events table

Revision ID: f1234567890c
Revises: e1234567890b
Create Date: 2026-01-25 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'f1234567890c'
down_revision: Union[str, Sequence[str], None] = 'e1234567890b'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table('unassigned_events',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('agent_id', sa.String(), nullable=True),
    sa.Column('phone_number', sa.String(), nullable=True),
    sa.Column('payload', sa.JSON(), nullable=True),
    sa.Column('created_at', sa.DateTime(), nullable=True),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_unassigned_events_agent_id'), 'unassigned_events', ['agent_id'], unique=False)
    op.create_index(op.f('ix_unassigned_events_id'), 'unassigned_events', ['id'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_unassigned_events_id'), table_name='unassigned_events')
    op.drop_index(op.f('ix_unassigned_events_agent_id'), table_name='unassigned_events')
    op.drop_table('unassigned_events')
