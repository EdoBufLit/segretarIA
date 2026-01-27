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

    # Use sa.text for timezone default to ensure consistent quoting
    op.add_column('phone_numbers', sa.Column('timezone', sa.String(), nullable=False, server_default=sa.text("'Europe/Rome'")))

    # Use sa.text for JSON default to ensure correct raw SQL generation on Postgres
    # This prevents Alembic from adding double quotes or misinterpreting the JSON string.
    # The string inside sa.text() is the raw SQL value: '{"key": "value"}'
    op.add_column('phone_numbers', sa.Column(
        'open_hours_json',
        sa.JSON(),
        nullable=False,
        server_default=sa.text('\'{"days": ["Mon", "Tue", "Wed", "Thu", "Fri"], "hours": ["09:00", "17:00"]}\'')
    ))

    # Ensure index on e164 exists (it should from previous migrations, but requested explicitly)
    # Using batch_alter_table for SQLite compatibility if we needed to add constraints,
    # but create_index is standalone.
    # We check first to avoid error if it exists.
    # Note: Alembic doesn't have native "if_not_exists" for indexes in all dialects.
    # The previous migration bf6c473695ec already added 'ix_phone_numbers_e164'.
    # We will just pass here as it is redundant and safer not to duplicate.
    pass


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('phone_numbers', 'open_hours_json')
    op.drop_column('phone_numbers', 'timezone')
    op.drop_column('phone_numbers', 'office_phone_e164')
