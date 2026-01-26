"""Add subscription_plan and plan_expires_at to users

Revision ID: bc611d0979a4
Revises: b48741909d28
Create Date: 2026-01-26 01:28:05.424976

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'bc611d0979a4'
down_revision: Union[str, Sequence[str], None] = 'b48741909d28'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    with op.batch_alter_table('users', schema=None) as batch_op:
        batch_op.add_column(sa.Column('subscription_plan', sa.String(), server_default='NONE', nullable=False))
        batch_op.add_column(sa.Column('plan_expires_at', sa.DateTime(), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    with op.batch_alter_table('users', schema=None) as batch_op:
        batch_op.drop_column('plan_expires_at')
        batch_op.drop_column('subscription_plan')
