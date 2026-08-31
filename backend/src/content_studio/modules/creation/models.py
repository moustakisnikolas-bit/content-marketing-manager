import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Numeric,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from content_studio.db.base import Base, TenantScopedMixin, TimestampMixin, UUIDPrimaryKeyMixin


class Asset(UUIDPrimaryKeyMixin, TimestampMixin, TenantScopedMixin, Base):
    """A stored file (upload or generated media). Phase 1 covers upload
    only; AssetRelationship/GenerationJob linkage arrives in Phase 2 with
    the rest of the content-creation lifecycle."""

    __tablename__ = "assets"
    __table_args__ = (
        ForeignKeyConstraint(
            ["organization_id"], ["organizations.id"], ondelete="CASCADE",
            name="fk_assets_organization_id_organizations",
        ),
    )

    workspace_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False, index=True
    )
    uploaded_by_user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    storage_key: Mapped[str] = mapped_column(String(500), nullable=False, unique=True)
    original_filename: Mapped[str] = mapped_column(String(300), nullable=False)
    content_type: Mapped[str] = mapped_column(String(150), nullable=False)
    byte_size: Mapped[int] = mapped_column(BigInteger, nullable=False)


# Content type values shared across ContentItem/GenerationJob/ContentRecipe.
# "audio" (Audio Studio v1) reuses this exact lifecycle rather than a
# separate module — voiceover/music generation via AIAudioPort, stored as
# an Asset through ContentRevision.asset_id, same as "image".
CONTENT_TYPES = ("text", "image", "audio")

# ContentItem.status
CONTENT_ITEM_STATUSES = ("draft", "in_review", "approved", "rejected")

# GenerationJob.status — mirrors the brief -> recipe -> estimate -> preview
# -> quality gate -> review -> package lifecycle from
# 05_AI_CONTENT_CREATION_MODULE.md.
GENERATION_JOB_STATUSES = (
    "pending",
    "generating",
    "quality_gate_failed",
    "awaiting_review",
    "approved",
    "rejected",
    "failed",
)

# GenerationAttempt.status
GENERATION_ATTEMPT_STATUSES = ("dispatched", "succeeded", "failed")

# ContentRevision.kind
REVISION_KINDS = ("draft_preview", "final_render")

# Review.decision
REVIEW_DECISIONS = ("approved", "rejected")


class ContentRecipe(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Catalog entity (not tenant-scoped — offered to every workspace):
    which provider/model/params to use for a content type, and the
    estimated cost used to reserve credits before generation starts."""

    __tablename__ = "content_recipes"
    __table_args__ = (
        CheckConstraint(f"content_type in {CONTENT_TYPES}", name="ck_content_recipe_content_type"),
    )

    name: Mapped[str] = mapped_column(String(100), nullable=False, unique=True)
    content_type: Mapped[str] = mapped_column(String(20), nullable=False)
    provider: Mapped[str] = mapped_column(String(50), nullable=False)
    model: Mapped[str] = mapped_column(String(100), nullable=False)
    estimated_cost: Mapped[Decimal] = mapped_column(Numeric(14, 4), nullable=False)
    params: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    is_active: Mapped[bool] = mapped_column(default=True, nullable=False)


class ContentItem(UUIDPrimaryKeyMixin, TimestampMixin, TenantScopedMixin, Base):
    """The logical thing being created (e.g. 'Instagram caption for the
    summer launch'). Owns zero or more GenerationJobs and ContentRevisions
    across its lifetime (regenerations create new jobs against the same
    item, not new items)."""

    __tablename__ = "content_items"
    __table_args__ = (
        ForeignKeyConstraint(
            ["organization_id"], ["organizations.id"], ondelete="CASCADE",
            name="fk_content_items_organization_id_organizations",
        ),
        CheckConstraint(f"content_type in {CONTENT_TYPES}", name="ck_content_item_content_type"),
        CheckConstraint(f"status in {CONTENT_ITEM_STATUSES}", name="ck_content_item_status"),
    )

    workspace_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False, index=True
    )
    brand_profile_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("brand_profiles.id", ondelete="SET NULL"), nullable=True
    )
    created_by_user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    content_type: Mapped[str] = mapped_column(String(20), nullable=False)
    title: Mapped[str] = mapped_column(String(300), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="draft")

    jobs: Mapped[list["GenerationJob"]] = relationship(back_populates="content_item")
    revisions: Mapped[list["ContentRevision"]] = relationship(back_populates="content_item")


class GenerationJob(UUIDPrimaryKeyMixin, TimestampMixin, TenantScopedMixin, Base):
    """One brief -> generation lifecycle instance. A regeneration is a new
    GenerationJob against the same ContentItem, not a mutation of this
    row — GenerationJob rows are effectively append-only history."""

    __tablename__ = "generation_jobs"
    __table_args__ = (
        ForeignKeyConstraint(
            ["organization_id"], ["organizations.id"], ondelete="CASCADE",
            name="fk_generation_jobs_organization_id_organizations",
        ),
        CheckConstraint(f"status in {GENERATION_JOB_STATUSES}", name="ck_generation_job_status"),
    )

    content_item_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("content_items.id", ondelete="CASCADE"), nullable=False, index=True
    )
    workspace_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False, index=True
    )
    recipe_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("content_recipes.id", ondelete="RESTRICT"), nullable=False
    )
    requested_by_user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    subscription_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("customer_subscriptions.id", ondelete="RESTRICT"), nullable=False
    )
    cost_reservation_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("cost_reservations.id", ondelete="SET NULL"), nullable=True
    )
    brief_text: Mapped[str] = mapped_column(Text, nullable=False)
    # Set only for image jobs generated from a real product photo (the
    # bulk product-campaign flow) — lets the image model edit the actual
    # photo instead of generating one from text alone. Null everywhere else.
    reference_image_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="pending")
    temporal_workflow_id: Mapped[str | None] = mapped_column(String(200), nullable=True, unique=True)
    failure_reason: Mapped[str | None] = mapped_column(Text, nullable=True)

    content_item: Mapped["ContentItem"] = relationship(back_populates="jobs")
    recipe: Mapped["ContentRecipe"] = relationship()
    attempts: Mapped[list["GenerationAttempt"]] = relationship(back_populates="job")


class GenerationAttempt(UUIDPrimaryKeyMixin, Base):
    """One actual provider call within a job. Append-only: a retry creates
    a new attempt row rather than overwriting the failed one, so the full
    dispatch history stays auditable."""

    __tablename__ = "generation_attempts"
    __table_args__ = (
        UniqueConstraint("generation_job_id", "attempt_number", name="uq_generation_attempt_job_number"),
        CheckConstraint(f"status in {GENERATION_ATTEMPT_STATUSES}", name="ck_generation_attempt_status"),
    )

    generation_job_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("generation_jobs.id", ondelete="CASCADE"), nullable=False, index=True
    )
    attempt_number: Mapped[int] = mapped_column(nullable=False)
    provider: Mapped[str] = mapped_column(String(50), nullable=False)
    model: Mapped[str] = mapped_column(String(100), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="dispatched")
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    actual_cost: Mapped[Decimal | None] = mapped_column(Numeric(14, 4), nullable=True)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    job: Mapped["GenerationJob"] = relationship(back_populates="attempts")


class ContentRevision(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """One version of a ContentItem's content — a draft preview from a
    successful GenerationAttempt, or (later) the promoted final render.
    Text content stores text_body directly; media content points at an
    Asset."""

    __tablename__ = "content_revisions"
    __table_args__ = (
        UniqueConstraint("content_item_id", "revision_number", name="uq_content_revision_item_number"),
        CheckConstraint(f"kind in {REVISION_KINDS}", name="ck_content_revision_kind"),
    )

    content_item_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("content_items.id", ondelete="CASCADE"), nullable=False, index=True
    )
    generation_attempt_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("generation_attempts.id", ondelete="SET NULL"), nullable=True
    )
    asset_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("assets.id", ondelete="SET NULL"), nullable=True
    )
    revision_number: Mapped[int] = mapped_column(nullable=False)
    kind: Mapped[str] = mapped_column(String(20), nullable=False, default="draft_preview")
    text_body: Mapped[str | None] = mapped_column(Text, nullable=True)

    content_item: Mapped["ContentItem"] = relationship(back_populates="revisions")
    reviews: Mapped[list["Review"]] = relationship(back_populates="revision")


class Review(UUIDPrimaryKeyMixin, Base):
    """A human decision on a ContentRevision. Append-only — a changed mind
    is a new Review row, not an edit of this one."""

    __tablename__ = "reviews"
    __table_args__ = (CheckConstraint(f"decision in {REVIEW_DECISIONS}", name="ck_review_decision"),)

    content_revision_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("content_revisions.id", ondelete="CASCADE"), nullable=False, index=True
    )
    reviewer_user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    decision: Mapped[str] = mapped_column(String(20), nullable=False)
    comment: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    revision: Mapped["ContentRevision"] = relationship(back_populates="reviews")


class ContentPackage(UUIDPrimaryKeyMixin, Base):
    """The finished, approved deliverable for a ContentItem."""

    __tablename__ = "content_packages"
    __table_args__ = (UniqueConstraint("content_item_id", name="uq_content_package_item"),)

    content_item_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("content_items.id", ondelete="CASCADE"), nullable=False
    )
    selected_revision_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("content_revisions.id", ondelete="RESTRICT"), nullable=False
    )
    packaged_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
