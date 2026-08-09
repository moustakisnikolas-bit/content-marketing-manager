import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Numeric,
    String,
    Text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from content_studio.db.base import Base, TenantScopedMixin, TimestampMixin, UUIDPrimaryKeyMixin

RECOMMENDATION_OUTCOME_STATUSES = ("acted_on", "dismissed", "expired")
EXPERIMENT_WINNERS = ("a", "b", "inconclusive")


class MetricDefinition(UUIDPrimaryKeyMixin, Base):
    """Catalog entity — the normalized metric vocabulary every provider's
    raw metric name gets mapped onto. Not tenant-scoped: every workspace
    shares the same definition of what 'engagement_rate' means."""

    __tablename__ = "metric_definitions"

    name: Mapped[str] = mapped_column(String(100), nullable=False, unique=True)
    unit: Mapped[str] = mapped_column(String(30), nullable=False)
    scope: Mapped[str] = mapped_column(String(30), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)


class MetricSnapshot(UUIDPrimaryKeyMixin, TenantScopedMixin, Base):
    """Dual storage, per 11_ANALYTICS_AND_OPTIMIZATION.md: raw_payload keeps
    the provider-native response verbatim (JSONB — genuinely variable
    shape per provider), normalized_value/unit is what every recommendation
    and comparison actually reads. Append-only: a metric refresh writes a
    new snapshot, never overwrites an old one."""

    __tablename__ = "metric_snapshots"
    __table_args__ = (
        ForeignKeyConstraint(
            ["organization_id"], ["organizations.id"], ondelete="CASCADE",
            name="fk_metric_snapshots_organization_id_organizations",
        ),
    )

    workspace_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False, index=True
    )
    metric_definition_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("metric_definitions.id", ondelete="RESTRICT"), nullable=False
    )
    publication_attempt_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("publication_attempts.id", ondelete="SET NULL"), nullable=True, index=True
    )
    campaign_plan_item_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("campaign_plan_items.id", ondelete="SET NULL"), nullable=True, index=True
    )
    raw_provider_name: Mapped[str] = mapped_column(String(100), nullable=False)
    raw_payload: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    normalized_value: Mapped[Decimal] = mapped_column(Numeric(18, 6), nullable=False)
    measurement_time: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    collection_time: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    attribution_window_days: Mapped[int | None] = mapped_column(nullable=True)
    currency: Mapped[str | None] = mapped_column(String(3), nullable=True)

    metric_definition: Mapped["MetricDefinition"] = relationship()


class ConversionEvent(UUIDPrimaryKeyMixin, TenantScopedMixin, Base):
    """Website/store conversion, tracked only where lawful basis and
    consent permit — per the recurring consent-gate rule across
    04_CORE_FEATURES.md, 09_RECOMMENDATION_ENGINE.md, 12_ECOMMERCE_MANAGER_MODULE.md."""

    __tablename__ = "conversion_events"
    __table_args__ = (
        ForeignKeyConstraint(
            ["organization_id"], ["organizations.id"], ondelete="CASCADE",
            name="fk_conversion_events_organization_id_organizations",
        ),
    )

    workspace_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False, index=True
    )
    campaign_plan_item_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("campaign_plan_items.id", ondelete="SET NULL"), nullable=True
    )
    event_type: Mapped[str] = mapped_column(String(50), nullable=False)
    value: Mapped[Decimal | None] = mapped_column(Numeric(14, 4), nullable=True)
    currency: Mapped[str | None] = mapped_column(String(3), nullable=True)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    consent_confirmed: Mapped[bool] = mapped_column(nullable=False, default=False)
    source: Mapped[str] = mapped_column(String(100), nullable=False)


class StrategyVersion(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Versions the recommendation *algorithm*, not tenant data — every
    Recommendation records which version produced it, so a later algorithm
    change doesn't retroactively reinterpret old explanations."""

    __tablename__ = "strategy_versions"

    name: Mapped[str] = mapped_column(String(100), nullable=False, unique=True)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    is_active: Mapped[bool] = mapped_column(nullable=False, default=True)


class Recommendation(UUIDPrimaryKeyMixin, TenantScopedMixin, Base):
    """Every field here exists to satisfy 09_RECOMMENDATION_ENGINE.md's
    explainability rule: 'must state low confidence when data insufficient;
    must not invent performance evidence.' evidence/sample_size/
    data_window_days are what makes a low-confidence recommendation
    honestly low-confidence rather than a bare unsupported claim."""

    __tablename__ = "recommendations"
    __table_args__ = (
        ForeignKeyConstraint(
            ["organization_id"], ["organizations.id"], ondelete="CASCADE",
            name="fk_recommendations_organization_id_organizations",
        ),
    )

    workspace_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False, index=True
    )
    strategy_version_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("strategy_versions.id", ondelete="RESTRICT"), nullable=False
    )
    recommendation_type: Mapped[str] = mapped_column(String(50), nullable=False)
    objective: Mapped[str] = mapped_column(String(300), nullable=False)
    score: Mapped[Decimal] = mapped_column(Numeric(10, 4), nullable=False)
    confidence: Mapped[str] = mapped_column(String(20), nullable=False)
    evidence: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    sample_size: Mapped[int] = mapped_column(nullable=False)
    data_window_days: Mapped[int] = mapped_column(nullable=False)
    explanation: Mapped[str] = mapped_column(Text, nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    outcomes: Mapped[list["RecommendationOutcome"]] = relationship(back_populates="recommendation")


class RecommendationOutcome(UUIDPrimaryKeyMixin, Base):
    """Whether a recommendation was actually acted on — every
    Recommendation must trace to one of these, per the Phase 5 exit
    criterion."""

    __tablename__ = "recommendation_outcomes"
    __table_args__ = (
        CheckConstraint(f"outcome in {RECOMMENDATION_OUTCOME_STATUSES}", name="ck_recommendation_outcome_status"),
    )

    recommendation_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("recommendations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    outcome: Mapped[str] = mapped_column(String(20), nullable=False)
    user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    recorded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    recommendation: Mapped["Recommendation"] = relationship(back_populates="outcomes")


class Experiment(UUIDPrimaryKeyMixin, TenantScopedMixin, Base):
    """A campaign-vs-campaign comparison on one metric. Deliberately not a
    live-running A/B test orchestrator (CampaignVariant was deferred from
    Phase 4) — this compares two already-run campaigns after the fact,
    still with the same non-causal-overclaiming discipline."""

    __tablename__ = "experiments"
    __table_args__ = (
        ForeignKeyConstraint(
            ["organization_id"], ["organizations.id"], ondelete="CASCADE",
            name="fk_experiments_organization_id_organizations",
        ),
        CheckConstraint(f"winner in {EXPERIMENT_WINNERS}", name="ck_experiment_winner"),
    )

    workspace_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(300), nullable=False)
    campaign_a_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("campaigns.id", ondelete="CASCADE"), nullable=False
    )
    campaign_b_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("campaigns.id", ondelete="CASCADE"), nullable=False
    )
    metric_definition_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("metric_definitions.id", ondelete="RESTRICT"), nullable=False
    )
    winner: Mapped[str] = mapped_column(String(20), nullable=False, default="inconclusive")
    evidence: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    result_summary: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class ModelVersion(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Deliberately dormant per the spec's explicit gating rule: 'add
    predictive models only after versioned training data, offline
    evaluation, controlled activation, drift monitoring, and rollback
    exist.' None of those exist yet, so nothing in this codebase creates,
    reads, or references rows here — the table exists so the eventual ML
    activation work has somewhere to start, per the entity catalog in
    18_DATABASE_SCHEMA_POSTGRESQL.md."""

    __tablename__ = "model_versions"

    name: Mapped[str] = mapped_column(String(100), nullable=False, unique=True)
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="not_activated")
