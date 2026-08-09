"""creation: add audio to CONTENT_TYPES

Revision ID: afdb6a9aafa5
Revises: 8266c8de1fad
Create Date: 2026-07-31 20:59:00.304262

"""
from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = 'afdb6a9aafa5'
down_revision: str | Sequence[str] | None = '8266c8de1fad'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Alembic's autogenerate doesn't diff CHECK constraint bodies (only
    presence/absence by name), so this constraint swap is hand-written —
    see windows_dev_gotchas.md if this surprises you twice."""
    op.drop_constraint("ck_content_recipe_content_type", "content_recipes", type_="check")
    op.create_check_constraint(
        "ck_content_recipe_content_type", "content_recipes", "content_type in ('text', 'image', 'audio')"
    )
    op.drop_constraint("ck_content_item_content_type", "content_items", type_="check")
    op.create_check_constraint(
        "ck_content_item_content_type", "content_items", "content_type in ('text', 'image', 'audio')"
    )


def downgrade() -> None:
    op.drop_constraint("ck_content_item_content_type", "content_items", type_="check")
    op.create_check_constraint(
        "ck_content_item_content_type", "content_items", "content_type in ('text', 'image')"
    )
    op.drop_constraint("ck_content_recipe_content_type", "content_recipes", type_="check")
    op.create_check_constraint(
        "ck_content_recipe_content_type", "content_recipes", "content_type in ('text', 'image')"
    )
