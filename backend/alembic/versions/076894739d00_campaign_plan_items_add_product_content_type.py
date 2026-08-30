"""marketing: add product_id and content_type to campaign_plan_items

Revision ID: 076894739d00
Revises: 74e547241ca1
Create Date: 2026-08-30 00:00:01.000000

"""
from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

# revision identifiers, used by Alembic.
revision: str = '076894739d00'
down_revision: str | Sequence[str] | None = '74e547241ca1'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        'campaign_plan_items',
        sa.Column('product_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('products.id', ondelete='SET NULL'), nullable=True),
    )
    # server_default backfills existing rows (all pre-existing items are
    # from the single-brief text flow) with the same default the model uses.
    op.add_column(
        'campaign_plan_items',
        sa.Column('content_type', sa.String(length=20), nullable=False, server_default='text'),
    )


def downgrade() -> None:
    op.drop_column('campaign_plan_items', 'content_type')
    op.drop_column('campaign_plan_items', 'product_id')
