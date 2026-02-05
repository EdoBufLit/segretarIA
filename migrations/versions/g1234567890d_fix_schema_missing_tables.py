"""Fix schema missing tables (notes, agent_routing)

Revision ID: g1234567890d
Revises: f1234567890c
Create Date: 2026-01-25 01:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'g1234567890d'
down_revision: Union[str, Sequence[str], None] = 'f1234567890c'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. Add notes to phone_numbers
    op.add_column('phone_numbers', sa.Column('notes', sa.String(), nullable=True))

    # 2. Create agent_routing table
    op.create_table('agent_routing',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('user_id', sa.Integer(), nullable=True),
    sa.Column('agent_id', sa.String(), nullable=False),
    sa.Column('phone_number_id', sa.Integer(), nullable=True),
    sa.Column('status', sa.String(), nullable=False, server_default="active"),
    sa.Column('is_active', sa.Boolean(), nullable=True, server_default="true"),
    sa.Column('created_at', sa.DateTime(), nullable=True),
    sa.Column('updated_at', sa.DateTime(), nullable=True),
    sa.Column('last_event_at', sa.DateTime(), nullable=True),
    sa.ForeignKeyConstraint(['phone_number_id'], ['phone_numbers.id'], ),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_agent_routing_id'), 'agent_routing', ['id'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_agent_routing_id'), table_name='agent_routing')
    op.drop_table('agent_routing')
    op.drop_column('phone_numbers', 'notes')
