"""commerce: add categories to products

Revision ID: 74e547241ca1
Revises: fe5a1aa94482
Create Date: 2026-08-30 00:00:00.000000

"""
from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

# revision identifiers, used by Alembic.
revision: str = '74e547241ca1'
down_revision: str | Sequence[str] | None = 'fe5a1aa94482'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # server_default backfills existing rows synced before this column
    # existed with an empty category list rather than NULL.
    op.add_column(
        'products',
        sa.Column('categories', postgresql.JSONB(), nullable=False, server_default='[]'),
    )


def downgrade() -> None:
    op.drop_column('products', 'categories')
