import uuid
from datetime import UTC, datetime
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from content_studio.modules.governance.models import (
    AgentRegistration,
    AuditEvent,
    ModerationDecision,
    PolicyDecisionReference,
    ToolApproval,
    ToolRegistration,
)


class GovernanceRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def add_event(
        self,
        *,
        organization_id: uuid.UUID | None,
        event_type: str,
        actor_type: str,
        actor_id: str | None,
        summary: str,
        payload: dict,
        request_id: str | None,
        correlation_id: str | None = None,
        trace_id: str | None = None,
        tool_call_id: str | None = None,
        workflow_id: str | None = None,
        business_operation_id: str | None = None,
    ) -> AuditEvent:
        event = AuditEvent(
            organization_id=organization_id,
            event_type=event_type,
            actor_type=actor_type,
            actor_id=actor_id,
            summary=summary,
            payload=payload,
            request_id=request_id,
            correlation_id=correlation_id,
            trace_id=trace_id,
            tool_call_id=tool_call_id,
            workflow_id=workflow_id,
            business_operation_id=business_operation_id,
        )
        self._session.add(event)
        await self._session.flush()
        return event

    async def list_events_for_organization(self, organization_id: uuid.UUID) -> list[AuditEvent]:
        result = await self._session.execute(
            select(AuditEvent)
            .where(AuditEvent.organization_id == organization_id)
            .order_by(AuditEvent.created_at.desc())
        )
        return list(result.scalars().all())

    async def list_events_for_correlation_id(self, correlation_id: str) -> list[AuditEvent]:
        """The exit-criterion query: 'one business action traces end-to-end
        through a single correlation id across all systems.'"""
        result = await self._session.execute(
            select(AuditEvent)
            .where(AuditEvent.correlation_id == correlation_id)
            .order_by(AuditEvent.created_at)
        )
        return list(result.scalars().all())

    # -- Agent registry ---------------------------------------------------

    async def create_agent(
        self, *, name: str, display_name: str, mcp_domain: str, description: str
    ) -> AgentRegistration:
        agent = AgentRegistration(name=name, display_name=display_name, mcp_domain=mcp_domain, description=description)
        self._session.add(agent)
        await self._session.flush()
        return agent

    async def get_agent_by_name(self, name: str) -> AgentRegistration | None:
        result = await self._session.execute(select(AgentRegistration).where(AgentRegistration.name == name))
        return result.scalar_one_or_none()

    async def get_agent_by_id(self, agent_id: uuid.UUID) -> AgentRegistration | None:
        return await self._session.get(AgentRegistration, agent_id)

    async def list_agents(self) -> list[AgentRegistration]:
        result = await self._session.execute(select(AgentRegistration).order_by(AgentRegistration.name))
        return list(result.scalars().all())

    # -- Tool registry ------------------------------------------------------

    async def create_tool(
        self,
        *,
        agent_id: uuid.UUID,
        name: str,
        version: str,
        risk_level: str,
        description: str,
        requires_approval: bool,
    ) -> ToolRegistration:
        tool = ToolRegistration(
            agent_id=agent_id, name=name, version=version, risk_level=risk_level, description=description,
            requires_approval=requires_approval,
        )
        self._session.add(tool)
        await self._session.flush()
        return tool

    async def get_tool_by_name_version(self, name: str, version: str) -> ToolRegistration | None:
        result = await self._session.execute(
            select(ToolRegistration).where(ToolRegistration.name == name, ToolRegistration.version == version)
        )
        return result.scalar_one_or_none()

    async def get_tool_by_id(self, tool_id: uuid.UUID) -> ToolRegistration | None:
        return await self._session.get(ToolRegistration, tool_id)

    async def list_tools(self) -> list[ToolRegistration]:
        result = await self._session.execute(select(ToolRegistration).order_by(ToolRegistration.name))
        return list(result.scalars().all())

    # -- Tool approvals ------------------------------------------------------

    async def create_tool_approval(
        self,
        *,
        organization_id: uuid.UUID,
        workspace_id: uuid.UUID,
        tool_registration_id: uuid.UUID,
        requested_by_user_id: uuid.UUID | None,
        payload_digest: str,
        expires_at: datetime,
        destination: str | None = None,
        cost: Decimal | None = None,
        correlation_id: str | None = None,
    ) -> ToolApproval:
        approval = ToolApproval(
            organization_id=organization_id, workspace_id=workspace_id, tool_registration_id=tool_registration_id,
            requested_by_user_id=requested_by_user_id, payload_digest=payload_digest, destination=destination,
            cost=cost, correlation_id=correlation_id, expires_at=expires_at,
        )
        self._session.add(approval)
        await self._session.flush()
        return approval

    async def get_tool_approval_by_id(self, approval_id: uuid.UUID) -> ToolApproval | None:
        return await self._session.get(ToolApproval, approval_id)

    async def find_valid_approval(
        self, *, tool_registration_id: uuid.UUID, workspace_id: uuid.UUID, payload_digest: str
    ) -> ToolApproval | None:
        """A 'valid' approval is approved, not yet used, not expired, and
        bound to this exact payload digest — the single-use binding rule."""
        now = datetime.now(UTC)
        result = await self._session.execute(
            select(ToolApproval).where(
                ToolApproval.tool_registration_id == tool_registration_id,
                ToolApproval.workspace_id == workspace_id,
                ToolApproval.payload_digest == payload_digest,
                ToolApproval.status == "approved",
                ToolApproval.used_at.is_(None),
                ToolApproval.expires_at > now,
            )
        )
        return result.scalars().first()

    async def approve_tool_approval(self, approval: ToolApproval, *, approved_by_user_id: uuid.UUID) -> None:
        approval.status = "approved"
        approval.approved_by_user_id = approved_by_user_id
        approval.approved_at = datetime.now(UTC)
        await self._session.flush()

    async def mark_tool_approval_used(self, approval: ToolApproval) -> None:
        approval.status = "used"
        approval.used_at = datetime.now(UTC)
        await self._session.flush()

    async def reject_tool_approval(self, approval: ToolApproval) -> None:
        approval.status = "rejected"
        await self._session.flush()

    async def list_pending_approvals_for_workspace(self, workspace_id: uuid.UUID) -> list[ToolApproval]:
        result = await self._session.execute(
            select(ToolApproval)
            .where(ToolApproval.workspace_id == workspace_id, ToolApproval.status == "pending")
            .order_by(ToolApproval.created_at.desc())
        )
        return list(result.scalars().all())

    # -- Policy decision references -----------------------------------------

    async def create_policy_decision_reference(
        self,
        *,
        organization_id: uuid.UUID | None,
        tool_registration_id: uuid.UUID | None,
        correlation_id: str | None,
        policy_path: str,
        decision: str,
        reasons: list[str],
        input_digest: str,
    ) -> PolicyDecisionReference:
        row = PolicyDecisionReference(
            organization_id=organization_id, tool_registration_id=tool_registration_id,
            correlation_id=correlation_id, policy_path=policy_path, decision=decision, reasons=reasons,
            input_digest=input_digest, evaluated_at=datetime.now(UTC),
        )
        self._session.add(row)
        await self._session.flush()
        return row

    # -- Moderation decisions ------------------------------------------------

    async def create_moderation_decision(
        self,
        *,
        organization_id: uuid.UUID | None,
        correlation_id: str | None,
        source: str,
        decision: str,
        detected_patterns: list[str],
        content_excerpt: str,
    ) -> ModerationDecision:
        row = ModerationDecision(
            organization_id=organization_id, correlation_id=correlation_id, source=source, decision=decision,
            detected_patterns=detected_patterns, content_excerpt=content_excerpt,
        )
        self._session.add(row)
        await self._session.flush()
        return row
