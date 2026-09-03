import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from content_studio.db.base import Base, TenantScopedMixin, TimestampMixin, UUIDPrimaryKeyMixin

# Named commitment from 10_SOCIAL_PUBLISHING_MODULE.md's Phase 3 list.
# Pinterest/LinkedIn/X/Google Business Profile are conditional expansion,
# not this phase's scope.
PLATFORMS = ("facebook", "instagram", "tiktok", "youtube")

CONNECTION_STATUSES = ("connected", "disconnected", "error", "token_expired")

# One row per (connection, capability) — never a hardcoded "platform X
# supports Y" table, per the spec's explicit rule. Capability names are
# free-form strings (e.g. "direct_publish_image"), not an enum, since the
# set of possible capabilities varies per platform and grows over time.
PUBLICATION_PLAN_STATUSES = (
    "draft",
    "pending_approval",
    "approved",
    "publishing",
    "published",
    "failed",
    "rejected",
    "cancelled",
)

PUBLICATION_ATTEMPT_STATUSES = ("dispatched", "succeeded", "failed")

# "post" covers text/image content_type as-is. "story" is Instagram-only
# (see ports/social_platform.py's publish_story — Facebook Stories are
# deliberately out of scope) and only meaningful for content_type="image".
TARGET_FORMATS = ("post", "story")


class PlatformConnection(UUIDPrimaryKeyMixin, TimestampMixin, TenantScopedMixin, Base):
    """A connected social account. Tokens are never stored directly —
    access_token_secret_ref/refresh_token_secret_ref are opaque references
    into OpenBao (see ports/secrets.py); this table only ever holds
    non-secret metadata, per 13_WOOCOMMERCE_PLUGIN_ARCHITECTURE.md's
    'no provider key ever stored in plaintext' rule generalized to every
    OAuth-connected platform."""

    __tablename__ = "platform_connections"
    __table_args__ = (
        ForeignKeyConstraint(
            ["organization_id"], ["organizations.id"], ondelete="CASCADE",
            name="fk_platform_connections_organization_id_organizations",
        ),
        CheckConstraint(f"platform in {PLATFORMS}", name="ck_platform_connection_platform"),
        CheckConstraint(f"status in {CONNECTION_STATUSES}", name="ck_platform_connection_status"),
    )

    workspace_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False, index=True
    )
    connected_by_user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    platform: Mapped[str] = mapped_column(String(20), nullable=False)
    external_account_id: Mapped[str] = mapped_column(String(200), nullable=False)
    external_account_name: Mapped[str] = mapped_column(String(300), nullable=False)
    access_token_secret_ref: Mapped[str] = mapped_column(String(300), nullable=False)
    refresh_token_secret_ref: Mapped[str | None] = mapped_column(String(300), nullable=True)
    scopes: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="connected")
    last_refreshed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    capabilities: Mapped[list["EffectiveCapability"]] = relationship(back_populates="connection")


class EffectiveCapability(UUIDPrimaryKeyMixin, Base):
    """Dynamically resolved per connection — never hardcoded. Re-resolved
    whenever a connection is (re)established or capabilities are
    explicitly refreshed."""

    __tablename__ = "effective_capabilities"
    __table_args__ = (
        UniqueConstraint("platform_connection_id", "capability", name="uq_effective_capability_conn_cap"),
    )

    platform_connection_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("platform_connections.id", ondelete="CASCADE"), nullable=False, index=True
    )
    capability: Mapped[str] = mapped_column(String(100), nullable=False)
    is_available: Mapped[bool] = mapped_column(Boolean, nullable=False)
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    resolved_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    connection: Mapped["PlatformConnection"] = relationship(back_populates="capabilities")


class PublicationPlan(UUIDPrimaryKeyMixin, TimestampMixin, TenantScopedMixin, Base):
    """One 'publish this content to this connected account' lifecycle
    instance — mirrors GenerationJob's role in Phase 2: the durable-workflow
    anchor, reused by workers/temporal for the same approval-gate pattern."""

    __tablename__ = "publication_plans"
    __table_args__ = (
        ForeignKeyConstraint(
            ["organization_id"], ["organizations.id"], ondelete="CASCADE",
            name="fk_publication_plans_organization_id_organizations",
        ),
        CheckConstraint(f"status in {PUBLICATION_PLAN_STATUSES}", name="ck_publication_plan_status"),
        CheckConstraint(f"target_format in {TARGET_FORMATS}", name="ck_publication_plan_target_format"),
    )

    workspace_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False, index=True
    )
    content_item_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("content_items.id", ondelete="CASCADE"), nullable=False, index=True
    )
    platform_connection_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("platform_connections.id", ondelete="RESTRICT"), nullable=False
    )
    created_by_user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    approved_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    scheduled_for: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    target_format: Mapped[str] = mapped_column(String(20), nullable=False, default="post")
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="draft")
    temporal_workflow_id: Mapped[str | None] = mapped_column(String(200), nullable=True, unique=True)
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    failure_reason: Mapped[str | None] = mapped_column(Text, nullable=True)

    # passive_deletes=True: without it, SQLAlchemy's ORM tries to manage
    # this relationship itself on delete by UPDATE-ing each attempt's FK to
    # NULL first, which fails against publication_plan_id's NOT NULL
    # constraint — confirmed live via delete_publication_plan()'s own test
    # (same gotcha as commerce/models.py's StoreConnection.capabilities).
    # Defers entirely to the DB's own ondelete="CASCADE" on that FK instead.
    attempts: Mapped[list["PublicationAttempt"]] = relationship(back_populates="plan", passive_deletes=True)


class PublicationAttempt(UUIDPrimaryKeyMixin, Base):
    """One actual dispatch to the platform API. Append-only, same pattern
    as GenerationAttempt."""

    __tablename__ = "publication_attempts"
    __table_args__ = (
        UniqueConstraint("publication_plan_id", "attempt_number", name="uq_publication_attempt_plan_number"),
        CheckConstraint(f"status in {PUBLICATION_ATTEMPT_STATUSES}", name="ck_publication_attempt_status"),
    )

    publication_plan_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("publication_plans.id", ondelete="CASCADE"), nullable=False, index=True
    )
    attempt_number: Mapped[int] = mapped_column(nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="dispatched")
    external_post_id: Mapped[str | None] = mapped_column(String(300), nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    plan: Mapped["PublicationPlan"] = relationship(back_populates="attempts")
    reconciliations: Mapped[list["Reconciliation"]] = relationship(back_populates="attempt")


class Reconciliation(UUIDPrimaryKeyMixin, Base):
    """A check that the platform's own record of the post matches what we
    expected — 'did it actually publish', not just an optimistic local
    flag, per the Phase 3 exit criterion."""

    __tablename__ = "reconciliations"

    publication_attempt_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("publication_attempts.id", ondelete="CASCADE"), nullable=False, index=True
    )
    checked_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    matches_expected: Mapped[bool] = mapped_column(Boolean, nullable=False)
    external_status: Mapped[str] = mapped_column(String(100), nullable=False)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    attempt: Mapped["PublicationAttempt"] = relationship(back_populates="reconciliations")
