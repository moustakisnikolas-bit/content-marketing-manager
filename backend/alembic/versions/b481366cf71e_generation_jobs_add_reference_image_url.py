"""creation: add reference_image_url to generation_jobs, switch product_image recipe to flux-kontext-pro

Revision ID: b481366cf71e
Revises: e6d1d1eaf6a1
Create Date: 2026-08-31 00:00:00.000000

"""
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = 'b481366cf71e'
down_revision: str | Sequence[str] | None = 'e6d1d1eaf6a1'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column('generation_jobs', sa.Column('reference_image_url', sa.Text(), nullable=True))
    # db/seed.py only inserts the "product_image" recipe row on a
    # never-seeded DB, so an already-seeded environment would otherwise
    # keep the old text-to-image model forever regardless of config/env
    # changes — flip the existing row directly. estimated_cost is treated
    # as a rough internal ledger figure elsewhere in this project, not
    # exact billing, so the same "good enough" bar applies here.
    op.execute(
        "UPDATE content_recipes SET model = 'black-forest-labs/flux-kontext-pro', estimated_cost = 0.08 "
        "WHERE name = 'product_image'"
    )


def downgrade() -> None:
    op.drop_column('generation_jobs', 'reference_image_url')
