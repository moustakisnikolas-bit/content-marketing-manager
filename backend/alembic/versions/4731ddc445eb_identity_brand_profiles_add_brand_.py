"""identity: brand_profiles add brand_pillars_description

Revision ID: 4731ddc445eb
Revises: 3c79ca77d873
Create Date: 2026-09-03 09:31:27.885298

"""
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = '4731ddc445eb'
down_revision: str | Sequence[str] | None = '3c79ca77d873'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column('brand_profiles', sa.Column('brand_pillars_description', sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column('brand_profiles', 'brand_pillars_description')
