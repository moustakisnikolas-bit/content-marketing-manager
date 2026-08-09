import hashlib
import json
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal

from sqlalchemy.ext.asyncio import AsyncSession

from content_studio.correlation import get_correlation_id
from content_studio.modules.governance.exceptions import ApprovalNotFound
from content_studio.modules.governance.models import ToolApproval
from content_studio.modules.governance.moderation import scan_untrusted_text
from content_studio.modules.governance.repository import GovernanceRepository
from content_studio.modules.governance.service import AuditService
from content_studio.ports.policy import PolicyPort

DEFAULT_APPROVAL_TTL_MINUTES = 15


def digest_payload(data: dict) -> str:
    """Canonical (sorted-key) JSON hash — the 'exact payload digest' every
    ToolApproval binds to, and what authorize_tool_call re-derives from the
    actual call payload to check the binding still matches."""
    canonical = json.dumps(data, sort_keys=True, default=str)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class ToolCallAuthorization:
    allowed: bool
    reasons: list[str]
    policy_decision_id: uuid.UUID
    moderation_decision_id: uuid.UUID | None


class ToolGovernanceService:
    """Governs every MCP tool call, per every rule in
    15_MCP_AGENTS_AND_SECURITY.md's Security Rules section:
    - registry checks (agent/tool must be registered and active)
    - OPA policy decision, recorded as a PolicyDecisionReference
    - single-use, payload-digest-bound approval consumption for
      requires_approval tools
    - a moderation scan of any untrusted external text before it can
      influence a tool call, recorded as a ModerationDecision
    - a full audit event, allowed or denied, carrying the correlation
      chain

    An agent/tool implementation (modules/mcp/tools/*) always calls
    authorize_tool_call() first and only proceeds into the wrapped
    Application Service if `allowed` is True — the governance check is
    structurally in front of the business logic, not bolted on after."""

    def __init__(self, session: AsyncSession, *, policy: PolicyPort) -> None:
        self._session = session
        self._repo = GovernanceRepository(session)
        self._audit = AuditService(session)
        self._policy = policy

    async def authorize_tool_call(
        self,
        *,
        agent_name: str,
        tool_name: str,
        tool_version: str,
        organization_id: uuid.UUID,
        workspace_id: uuid.UUID,
        payload: dict,
        untrusted_text: str | None = None,
        untrusted_source: str = "tool_input",
    ) -> ToolCallAuthorization:
        agent = await self._repo.get_agent_by_name(agent_name)
        tool = await self._repo.get_tool_by_name_version(tool_name, tool_version)

        moderation_decision_id: uuid.UUID | None = None
        moderation_blocked = False
        if untrusted_text:
            scan = scan_untrusted_text(untrusted_text)
            moderation_row = await self._repo.create_moderation_decision(
                organization_id=organization_id,
                correlation_id=get_correlation_id(),
                source=untrusted_source,
                decision="allowed" if scan.allowed else "blocked",
                detected_patterns=scan.detected_patterns,
                content_excerpt=scan.excerpt,
            )
            moderation_decision_id = moderation_row.id
            moderation_blocked = not scan.allowed

        payload_digest = digest_payload(payload)
        matching_approval: ToolApproval | None = None
        if tool is not None and tool.requires_approval:
            matching_approval = await self._repo.find_valid_approval(
                tool_registration_id=tool.id, workspace_id=workspace_id, payload_digest=payload_digest
            )

        policy_input = {
            "agent_status": agent.status if agent is not None else "disabled",
            "tool_status": tool.status if tool is not None else "disabled",
            "risk_level": tool.risk_level if tool is not None else "high",
            "has_valid_approval": matching_approval is not None,
            "moderation_blocked": moderation_blocked,
        }
        policy_result = await self._policy.evaluate(policy_path="content_studio.mcp_tools", input_data=policy_input)
        allow = bool(policy_result.get("allow", False))
        reasons = list(policy_result.get("deny_reasons", []))

        policy_row = await self._repo.create_policy_decision_reference(
            organization_id=organization_id,
            tool_registration_id=tool.id if tool is not None else None,
            correlation_id=get_correlation_id(),
            policy_path="content_studio.mcp_tools",
            decision="allow" if allow else "deny",
            reasons=reasons,
            input_digest=digest_payload(policy_input),
        )

        if allow and matching_approval is not None:
            await self._repo.mark_tool_approval_used(matching_approval)

        await self._audit.record(
            event_type="governance.tool_call_authorized" if allow else "governance.tool_call_denied",
            actor_type="agent",
            actor_id=agent_name,
            organization_id=organization_id,
            summary=f"{'Authorized' if allow else 'Denied'} {tool_name}@{tool_version} for agent {agent_name}"
            + (f" ({', '.join(reasons)})" if reasons else ""),
            payload={
                "tool_name": tool_name, "tool_version": tool_version, "payload_digest": payload_digest,
                "policy_decision_id": str(policy_row.id),
            },
        )
        await self._session.commit()
        return ToolCallAuthorization(
            allowed=allow, reasons=reasons, policy_decision_id=policy_row.id,
            moderation_decision_id=moderation_decision_id,
        )

    async def request_tool_approval(
        self,
        *,
        organization_id: uuid.UUID,
        workspace_id: uuid.UUID,
        tool_registration_id: uuid.UUID,
        requested_by_user_id: uuid.UUID | None,
        payload: dict,
        destination: str | None = None,
        cost: Decimal | None = None,
        ttl_minutes: int = DEFAULT_APPROVAL_TTL_MINUTES,
    ) -> ToolApproval:
        approval = await self._repo.create_tool_approval(
            organization_id=organization_id, workspace_id=workspace_id, tool_registration_id=tool_registration_id,
            requested_by_user_id=requested_by_user_id, payload_digest=digest_payload(payload),
            expires_at=datetime.now(UTC) + timedelta(minutes=ttl_minutes), destination=destination,
            cost=cost, correlation_id=get_correlation_id(),
        )
        await self._audit.record(
            event_type="governance.tool_approval_requested",
            actor_type="user",
            actor_id=str(requested_by_user_id) if requested_by_user_id else None,
            organization_id=organization_id,
            summary="Requested approval for a high-risk tool call",
            payload={"approval_id": str(approval.id), "tool_registration_id": str(tool_registration_id)},
        )
        await self._session.commit()
        return approval

    async def approve_tool_approval(self, approval_id: uuid.UUID, *, approved_by_user_id: uuid.UUID) -> ToolApproval:
        approval = await self._repo.get_tool_approval_by_id(approval_id)
        if approval is None:
            raise ApprovalNotFound(str(approval_id))
        await self._repo.approve_tool_approval(approval, approved_by_user_id=approved_by_user_id)
        await self._audit.record(
            event_type="governance.tool_approval_granted",
            actor_type="user",
            actor_id=str(approved_by_user_id),
            organization_id=approval.organization_id,
            summary="Approved a high-risk tool call — explicit, single-use confirmation",
            payload={"approval_id": str(approval.id)},
        )
        await self._session.commit()
        return approval
