"""creation module: text_edit_learnings

Revision ID: ab0af2c59831
Revises: b481366cf71e
Create Date: 2026-09-02 00:00:00.000000

"""
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = 'ab0af2c59831'
down_revision: str | Sequence[str] | None = 'b481366cf71e'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table('text_edit_learnings',
    sa.Column('workspace_id', sa.UUID(), nullable=False),
    sa.Column('source_content_revision_id', sa.UUID(), nullable=False),
    sa.Column('deleted_text', sa.Text(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('organization_id', sa.UUID(), nullable=False),
    sa.ForeignKeyConstraint(['organization_id'], ['organizations.id'], name=op.f('fk_text_edit_learnings_organization_id_organizations'), ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['source_content_revision_id'], ['content_revisions.id'], name=op.f('fk_text_edit_learnings_source_content_revision_id_content_revisions'), ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['workspace_id'], ['workspaces.id'], name=op.f('fk_text_edit_learnings_workspace_id_workspaces'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_text_edit_learnings'))
    )
    op.create_index(op.f('ix_text_edit_learnings_organization_id'), 'text_edit_learnings', ['organization_id'], unique=False)
    op.create_index(op.f('ix_text_edit_learnings_workspace_id'), 'text_edit_learnings', ['workspace_id'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_text_edit_learnings_workspace_id'), table_name='text_edit_learnings')
    op.drop_index(op.f('ix_text_edit_learnings_organization_id'), table_name='text_edit_learnings')
    op.drop_table('text_edit_learnings')
