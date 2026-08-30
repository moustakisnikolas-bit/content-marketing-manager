"""identity: add product_line_description to brand_profiles

Revision ID: e6d1d1eaf6a1
Revises: 076894739d00
Create Date: 2026-08-30 00:00:02.000000

"""
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = 'e6d1d1eaf6a1'
down_revision: str | Sequence[str] | None = '076894739d00'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column('brand_profiles', sa.Column('product_line_description', sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column('brand_profiles', 'product_line_description')
