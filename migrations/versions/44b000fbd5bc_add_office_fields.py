"""add_office_fields

Revision ID: 44b000fbd5bc
Revises: bc611d0979a4
Create Date: 2026-01-27 03:20:26.668176

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '44b000fbd5bc'
down_revision: Union[str, Sequence[str], None] = 'bc611d0979a4'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column('phone_numbers', sa.Column('office_phone_e164', sa.String(), nullable=True))
    op.add_column('phone_numbers', sa.Column('timezone', sa.String(), nullable=False, server_default='Europe/Rome'))
    op.add_column('phone_numbers', sa.Column('open_hours_json', sa.JSON(), nullable=False, server_default='{"days": ["Mon", "Tue", "Wed", "Thu", "Fri"], "hours": ["09:00", "17:00"]}'))


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('phone_numbers', 'open_hours_json')
    op.drop_column('phone_numbers', 'timezone')
    op.drop_column('phone_numbers', 'office_phone_e164')
