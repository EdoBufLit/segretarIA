"""merge heads

Revision ID: 191cc4659d01
Revises: 18eef4f95ebb, 20260128183530, 44b000fbd5bc
Create Date: 2026-01-28 19:40:05.924532

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '191cc4659d01'
down_revision: Union[str, Sequence[str], None] = ('18eef4f95ebb', '20260128183530', '44b000fbd5bc')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    pass


def downgrade() -> None:
    """Downgrade schema."""
    pass
