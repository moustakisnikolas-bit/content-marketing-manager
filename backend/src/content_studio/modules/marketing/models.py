import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    Boolean,
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

# The 10 supported goals from 07_AI_MARKETING_MANAGER_MODULE.md.
GOAL_SLUGS = (
    "more_sales",
    "more_messages_bookings",
    "more_website_traffic",
    "more_followers_engagement",
    "brand_awareness",
    "product_service_launch",
    "offer_announcement",
    "product_education",
    "retargeting",
    "seasonal_evergreen_promotion",
)

BRIEF_MODES = ("manual", "guided", "autopilot")
PROPOSAL_STATUSES = ("draft", "approved", "rejected")
CAMPAIGN_STATUSES = ("planning", "active", "completed", "cancelled")
PLAN_ITEM_STATUSES = ("pending", "generating", "awaiting_review", "scheduled", "published", "failed", "skipped", "cancelled")
DECISION_TYPES = ("proposal_generated", "autopilot_proceed", "autopilot_skipped", "autopilot_halted")


class MarketingGoal(UUIDPrimaryKeyMixin, Base):
    """Catalog entity (not tenant-scoped) — the 10 supported goals."""

    __tablename__ = "marketing_goals"
    __table_args__ = (CheckConstraint(f"slug in {GOAL_SLUGS}", name="ck_marketing_goal_slug"),)

    slug: Mapped[str] = mapped_column(String(50), nullable=False, unique=True)
    label: Mapped[str] = mapped_column(String(150), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)


class MarketingBrief(UUIDPrimaryKeyMixin, TimestampMixin, TenantScopedMixin, Base):
    """What the user submits in the goal wizard — 'choose what to promote,
    add inputs, choose mode, choose platforms, choose goal' (steps 1-5 of
    the 8-step wizard in 07_AI_MARKETING_MANAGER_MODULE.md)."""

    __tablename__ = "marketing_briefs"
    __table_args__ = (
        ForeignKeyConstraint(
            ["organization_id"], ["organizations.id"], ondelete="CASCADE",
            name="fk_marketing_briefs_organization_id_organizations",
        ),
        CheckConstraint(f"mode in {BRIEF_MODES}", name="ck_marketing_brief_mode"),
    )

    workspace_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False, index=True
    )
    created_by_user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    goal_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("marketing_goals.id", ondelete="RESTRICT"), nullable=False
    )
    what_to_promote: Mapped[str] = mapped_column(Text, nullable=False)
    mode: Mapped[str] = mapped_column(String(20), nullable=False)
    target_platforms: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list)

    proposals: Mapped[list["CampaignProposal"]] = relationship(back_populates="brief")


class CampaignProposal(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Step 6-7 of the wizard: 'receive campaign proposal' / 'approve, edit,
    regenerate'. Never claims certainty — assumptions/confidence/
    explanation are first-class fields, not an afterthought, per the
    spec's explicit anti-overclaiming rule."""

    __tablename__ = "campaign_proposals"

    brief_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("marketing_briefs.id", ondelete="CASCADE"), nullable=False, index=True
    )
    objective: Mapped[str] = mapped_column(String(300), nullable=False)
    assumptions: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list)
    plan_summary: Mapped[str] = mapped_column(Text, nullable=False)
    # Structured form of the plan shown to the user — [{title, brief_text,
    # platform}, ...]. Approval creates CampaignPlanItems from exactly this,
    # not a re-derived plan, so what was approved is what gets built even
    # though the generator itself is deterministic.
    plan_items_draft: Mapped[list[dict]] = mapped_column(JSONB, nullable=False, default=list)
    estimated_cost: Mapped[Decimal] = mapped_column(Numeric(14, 4), nullable=False)
    explanation: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="draft")

    brief: Mapped["MarketingBrief"] = relationship(back_populates="proposals")
    campaign: Mapped["Campaign | None"] = relationship(back_populates="proposal", uselist=False)


class Campaign(UUIDPrimaryKeyMixin, TimestampMixin, TenantScopedMixin, Base):
    """The approved, running campaign — created once a CampaignProposal is
    approved. Owns the individual pieces of content/publication work as
    CampaignPlanItems."""

    __tablename__ = "campaigns"
    __table_args__ = (
        ForeignKeyConstraint(
            ["organization_id"], ["organizations.id"], ondelete="CASCADE",
            name="fk_campaigns_organization_id_organizations",
        ),
        CheckConstraint(f"status in {CAMPAIGN_STATUSES}", name="ck_campaign_status"),
    )

    workspace_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False, index=True
    )
    proposal_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("campaign_proposals.id", ondelete="RESTRICT"), nullable=False, unique=True
    )
    approved_by_user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    name: Mapped[str] = mapped_column(String(300), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="planning")
    temporal_workflow_id: Mapped[str | None] = mapped_column(String(200), nullable=True, unique=True)
    # Running total settled so far — the OPA spend-limit guardrail checks
    # this plus the next item's estimated cost against AutoPilotPolicy.
    # Only Auto-Pilot mode updates this; Manual/Guided spend is tracked
    # through the ledger directly since each item requires human approval.
    total_spent: Mapped[Decimal] = mapped_column(Numeric(14, 4), nullable=False, default=Decimal(0))

    proposal: Mapped["CampaignProposal"] = relationship(back_populates="campaign")
    plan_items: Mapped[list["CampaignPlanItem"]] = relationship(back_populates="campaign")
    autopilot_policy: Mapped["AutoPilotPolicy | None"] = relationship(back_populates="campaign", uselist=False)


class CampaignPlanItem(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """One planned piece of content + its publication, within a campaign.
    content_item_id/publication_plan_id are set once the corresponding
    Phase 2/3 workflow is actually started — a campaign orchestrates
    existing generation/publishing infrastructure rather than
    reimplementing it."""

    __tablename__ = "campaign_plan_items"

    campaign_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("campaigns.id", ondelete="CASCADE"), nullable=False, index=True
    )
    sequence_number: Mapped[int] = mapped_column(nullable=False)
    title: Mapped[str] = mapped_column(String(300), nullable=False)
    brief_text: Mapped[str] = mapped_column(Text, nullable=False)
    # The proposal's intended platform (e.g. "facebook") — decoupled from
    # platform_connection_id, which is only resolved to an actual
    # connected account at dispatch time (proposals are generated before
    # we know which specific connection will be used).
    target_platform: Mapped[str | None] = mapped_column(String(20), nullable=True)
    platform_connection_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("platform_connections.id", ondelete="SET NULL"), nullable=True
    )
    content_item_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("content_items.id", ondelete="SET NULL"), nullable=True
    )
    generation_job_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("generation_jobs.id", ondelete="SET NULL"), nullable=True
    )
    publication_plan_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("publication_plans.id", ondelete="SET NULL"), nullable=True
    )
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="pending")

    campaign: Mapped["Campaign"] = relationship(back_populates="plan_items")


class CampaignDecision(UUIDPrimaryKeyMixin, Base):
    """Append-only explainability record — 'internal decision/evidence
    record' from the Campaign Proposal spec, and the record of every
    Auto-Pilot action and why it was (or wasn't) taken."""

    __tablename__ = "campaign_decisions"
    __table_args__ = (CheckConstraint(f"decision_type in {DECISION_TYPES}", name="ck_campaign_decision_type"),)

    campaign_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("campaigns.id", ondelete="CASCADE"), nullable=False, index=True
    )
    plan_item_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("campaign_plan_items.id", ondelete="SET NULL"), nullable=True
    )
    decision_type: Mapped[str] = mapped_column(String(30), nullable=False)
    explanation: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class AutoPilotPolicy(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """The guardrails a campaign's Auto-Pilot workflow must respect,
    evaluated via OPA before every autonomous action — never bypassable
    from application code, matching the spec's 'cannot bypass rights,
    moderation, platform capability, OPA policy... or audit' rule."""

    __tablename__ = "autopilot_policies"
    __table_args__ = (UniqueConstraint("campaign_id", name="uq_autopilot_policy_campaign"),)

    campaign_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("campaigns.id", ondelete="CASCADE"), nullable=False
    )
    created_by_user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    allowed_platforms: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list)
    max_total_spend: Mapped[Decimal] = mapped_column(Numeric(14, 4), nullable=False)
    blocked_topics: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list)
    posting_window_start_hour: Mapped[int] = mapped_column(nullable=False, default=0)
    posting_window_end_hour: Mapped[int] = mapped_column(nullable=False, default=23)
    kill_switch_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    campaign: Mapped["Campaign"] = relationship(back_populates="autopilot_policy")
