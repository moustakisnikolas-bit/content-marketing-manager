"""marketing: campaign_plan_items add source_plan_item_id

Revision ID: 3c79ca77d873
Revises: ab0af2c59831
Create Date: 2026-09-02 00:00:00.000000

"""
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = '3c79ca77d873'
down_revision: str | Sequence[str] | None = 'ab0af2c59831'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column('campaign_plan_items', sa.Column('source_plan_item_id', sa.UUID(), nullable=True))
    op.create_foreign_key(
        op.f('fk_campaign_plan_items_source_plan_item_id_campaign_plan_items'),
        'campaign_plan_items', 'campaign_plan_items',
        ['source_plan_item_id'], ['id'], ondelete='SET NULL',
    )


def downgrade() -> None:
    op.drop_constraint(
        op.f('fk_campaign_plan_items_source_plan_item_id_campaign_plan_items'),
        'campaign_plan_items', type_='foreignkey',
    )
    op.drop_column('campaign_plan_items', 'source_plan_item_id')
