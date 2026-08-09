"""publishing: add target_format to publication_plans

Revision ID: fe5a1aa94482
Revises: afdb6a9aafa5
Create Date: 2026-08-06 19:42:58.823894

"""
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = 'fe5a1aa94482'
down_revision: str | Sequence[str] | None = 'afdb6a9aafa5'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # server_default backfills existing rows (this table isn't empty in a
    # dev environment that's already been exercised); autogenerate also
    # doesn't add CHECK constraints reliably, so both are hand-written —
    # see windows_dev_gotchas.md.
    op.add_column(
        'publication_plans',
        sa.Column('target_format', sa.String(length=20), nullable=False, server_default='post'),
    )
    op.create_check_constraint(
        "ck_publication_plan_target_format", "publication_plans", "target_format in ('post', 'story')"
    )


def downgrade() -> None:
    op.drop_constraint("ck_publication_plan_target_format", "publication_plans", type_="check")
    op.drop_column('publication_plans', 'target_format')
