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
    func,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from content_studio.db.base import Base, TenantScopedMixin, TimestampMixin, UUIDPrimaryKeyMixin

# The 8 named agents from 15_MCP_AGENTS_AND_SECURITY.md, each wrapping
# *existing* Application Services — an agent never carries its own
# business logic, only governed exposure of what Phases 1-6 already built.
AGENT_NAMES = (
    "marketing_manager",
    "campaign_planner",
    "creation_coordinator",
    "publishing",
    "analytics_recommendation",
    "ecommerce",
    "audio_guide",
    "support",
)

# The 12 MCP domains — a superset of the 8 agents above; not every domain
# has a dedicated named agent yet (e.g. "knowledge", "connections",
# "distribution", "billing" are cross-cutting, not agent-specific).
MCP_DOMAINS = (
    "knowledge", "marketing", "planning", "commerce", "generation", "audio",
    "connections", "publishing", "analytics", "distribution", "billing", "support",
)

AGENT_STATUSES = ("active", "disabled")
TOOL_STATUSES = ("active", "disabled")
TOOL_RISK_LEVELS = ("low", "medium", "high")
TOOL_APPROVAL_STATUSES = ("pending", "approved", "rejected", "expired", "used")
POLICY_DECISIONS = ("allow", "deny")
MODERATION_DECISIONS = ("allowed", "blocked")


class AuditEvent(UUIDPrimaryKeyMixin, Base):
    """Append-only business audit log — the authoritative chain described
    in 16_AUDIT_TRAIL_AND_APPROVALS.md: human intent -> agent decision ->
    MCP tool -> OPA policy -> Temporal approval -> application action ->
    provider result -> cost -> reconciliation.

    Phase 1 populates request_id only; the remaining correlation ids exist
    as columns now (to avoid a schema change later) but are only fully
    wired across gateway/OPA/Temporal/Langfuse/OpenBao/workers in Phase 7.

    No TimestampMixin: only created_at, never updated_at — an audit event
    is never modified after it is written."""

    __tablename__ = "audit_events"
    __table_args__ = (
        ForeignKeyConstraint(
            ["organization_id"], ["organizations.id"], ondelete="SET NULL",
            name="fk_audit_events_organization_id_organizations",
        ),
    )

    # Nullable: some events (health checks, platform-level admin actions)
    # are not tenant-scoped, unlike the TenantScopedMixin convention used
    # by business entities.
    organization_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), nullable=True, index=True
    )

    event_type: Mapped[str] = mapped_column(String(150), nullable=False, index=True)
    actor_type: Mapped[str] = mapped_column(String(20), nullable=False)
    actor_id: Mapped[str | None] = mapped_column(String(200), nullable=True)
    summary: Mapped[str] = mapped_column(String(500), nullable=False)
    payload: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)

    request_id: Mapped[str | None] = mapped_column(String(100), nullable=True, index=True)
    correlation_id: Mapped[str | None] = mapped_column(String(100), nullable=True, index=True)
    trace_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    tool_call_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    workflow_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    business_operation_id: Mapped[str | None] = mapped_column(String(100), nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class AgentRegistration(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Catalog entity, not tenant-scoped — every workspace sees the same
    set of named agents. 'Formalizing the 8 named agents' (this phase's
    exit deliverable) means each one gets a real row here, with a real
    MCP domain, not just a name in a spec document."""

    __tablename__ = "agent_registrations"
    __table_args__ = (
        CheckConstraint(f"name in {AGENT_NAMES}", name="ck_agent_registration_name"),
        CheckConstraint(f"mcp_domain in {MCP_DOMAINS}", name="ck_agent_registration_mcp_domain"),
        CheckConstraint(f"status in {AGENT_STATUSES}", name="ck_agent_registration_status"),
    )

    name: Mapped[str] = mapped_column(String(100), nullable=False, unique=True)
    display_name: Mapped[str] = mapped_column(String(200), nullable=False)
    mcp_domain: Mapped[str] = mapped_column(String(50), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="active")


class ToolRegistration(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """One row per (tool name, version) — the 'tool/version allowlist'
    security rule: a tool call for a name/version not registered here (or
    registered but disabled) is refused before it ever reaches an
    Application Service."""

    __tablename__ = "tool_registrations"
    __table_args__ = (
        UniqueConstraint("name", "version", name="uq_tool_registration_name_version"),
        CheckConstraint(f"risk_level in {TOOL_RISK_LEVELS}", name="ck_tool_registration_risk_level"),
        CheckConstraint(f"status in {TOOL_STATUSES}", name="ck_tool_registration_status"),
    )

    agent_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("agent_registrations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(150), nullable=False)
    version: Mapped[str] = mapped_column(String(20), nullable=False)
    risk_level: Mapped[str] = mapped_column(String(20), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    # High-risk tools require a matching, unused, unexpired ToolApproval
    # before they execute — the 'explicit approval for high-impact
    # actions' rule. Low/medium-risk tools can be allowed straight through
    # by OPA without one.
    requires_approval: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="active")


class ToolApproval(UUIDPrimaryKeyMixin, TenantScopedMixin, Base):
    """A single-use approval binding, per 16_AUDIT_TRAIL_AND_APPROVALS.md:
    'binds to exact payload digest, tool/version, destination/account,
    cost, expiry, and approver.' Consuming it (marking used_at) and
    verifying the digest match happen atomically in GovernanceService, so
    an approval can never be replayed against a different payload or used
    twice."""

    __tablename__ = "tool_approvals"
    __table_args__ = (
        ForeignKeyConstraint(
            ["organization_id"], ["organizations.id"], ondelete="CASCADE",
            name="fk_tool_approvals_organization_id_organizations",
        ),
        CheckConstraint(f"status in {TOOL_APPROVAL_STATUSES}", name="ck_tool_approval_status"),
    )

    workspace_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False, index=True
    )
    tool_registration_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tool_registrations.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    requested_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    approved_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    payload_digest: Mapped[str] = mapped_column(String(64), nullable=False)
    destination: Mapped[str | None] = mapped_column(String(300), nullable=True)
    cost: Mapped[Decimal | None] = mapped_column(Numeric(14, 4), nullable=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="pending")
    correlation_id: Mapped[str | None] = mapped_column(String(100), nullable=True, index=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())


class PolicyDecisionReference(UUIDPrimaryKeyMixin, Base):
    """Links one OPA evaluation to the correlation chain, so the audit
    trail's 'MCP tool -> OPA policy' step is a real, queryable row, not
    something inferred from nearby timestamps. input_digest (not the raw
    input) avoids storing tool-call payloads a second time — AuditEvent
    already carries the full payload for the same correlation_id."""

    __tablename__ = "policy_decision_references"
    __table_args__ = (
        ForeignKeyConstraint(
            ["organization_id"], ["organizations.id"], ondelete="SET NULL",
            name="fk_policy_decision_references_organization_id_organizations",
        ),
        CheckConstraint(f"decision in {POLICY_DECISIONS}", name="ck_policy_decision_reference_decision"),
    )

    organization_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True, index=True)
    tool_registration_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tool_registrations.id", ondelete="SET NULL"), nullable=True
    )
    correlation_id: Mapped[str | None] = mapped_column(String(100), nullable=True, index=True)
    policy_path: Mapped[str] = mapped_column(String(200), nullable=False)
    decision: Mapped[str] = mapped_column(String(10), nullable=False)
    reasons: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list)
    input_digest: Mapped[str] = mapped_column(String(64), nullable=False)
    evaluated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class ModerationDecision(UUIDPrimaryKeyMixin, Base):
    """The audit record behind the 'untrusted content never treated as
    instruction' rule: every piece of externally-sourced text an agent
    tool call would otherwise interpolate into an AI-facing prompt is
    scanned first (modules/governance/moderation.py — deterministic
    pattern matching, no ML), and the decision is recorded here whether it
    passed or was blocked."""

    __tablename__ = "moderation_decisions"
    __table_args__ = (
        ForeignKeyConstraint(
            ["organization_id"], ["organizations.id"], ondelete="SET NULL",
            name="fk_moderation_decisions_organization_id_organizations",
        ),
        CheckConstraint(f"decision in {MODERATION_DECISIONS}", name="ck_moderation_decision_decision"),
    )

    organization_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True, index=True)
    correlation_id: Mapped[str | None] = mapped_column(String(100), nullable=True, index=True)
    source: Mapped[str] = mapped_column(String(100), nullable=False)
    decision: Mapped[str] = mapped_column(String(10), nullable=False)
    detected_patterns: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list)
    content_excerpt: Mapped[str] = mapped_column(String(500), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
