import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, status
from mcp.types import CallToolResult, InputRequiredResult
from sqlalchemy.ext.asyncio import AsyncSession

from content_studio.api.deps import (
    WorkspaceContext,
    get_current_user,
    get_db_session,
    get_policy,
    get_secrets,
    get_store_adapter,
    get_workspace_context,
)
from content_studio.mcp.context import AgentContext
from content_studio.mcp.server import build_agent_mcp_server
from content_studio.modules.governance.exceptions import ApprovalNotFound
from content_studio.modules.governance.repository import GovernanceRepository
from content_studio.modules.governance.schemas import (
    AgentOut,
    AuditEventOut,
    CallGenerateBestPostingTimeRequest,
    CallGenerateProductCampaignRequest,
    RequestToolApprovalRequest,
    ToolApprovalOut,
    ToolCallResultOut,
    ToolOut,
)
from content_studio.modules.governance.tool_governance import ToolGovernanceService
from content_studio.modules.identity.models import User
from content_studio.ports.policy import PolicyPort
from content_studio.ports.secrets import SecretsPort

router = APIRouter(prefix="/governance", tags=["governance"])


def _structured_result(call_result: CallToolResult | InputRequiredResult) -> dict:
    """Neither governed tool uses the SDK's Resolve(...) multi-round input
    flow, so a call_tool() response is always a CallToolResult here, never
    an InputRequiredResult — this assert makes that invariant explicit for
    both mypy and any future tool that might actually need that flow."""
    assert isinstance(call_result, CallToolResult), (
        "governed tools don't use Resolve(...); an InputRequiredResult would mean one now does"
    )
    return call_result.structured_content or {}


@router.get("/agents", response_model=list[AgentOut])
async def list_agents(session: AsyncSession = Depends(get_db_session)) -> list[AgentOut]:
    repo = GovernanceRepository(session)
    agents = await repo.list_agents()
    return [AgentOut.model_validate(a) for a in agents]


@router.get("/tools", response_model=list[ToolOut])
async def list_tools(session: AsyncSession = Depends(get_db_session)) -> list[ToolOut]:
    repo = GovernanceRepository(session)
    tools = await repo.list_tools()
    return [ToolOut.model_validate(t) for t in tools]


@router.post("/approvals", response_model=ToolApprovalOut, status_code=status.HTTP_201_CREATED)
async def request_tool_approval(
    body: RequestToolApprovalRequest,
    current_user: User = Depends(get_current_user),
    context: WorkspaceContext = Depends(get_workspace_context),
    session: AsyncSession = Depends(get_db_session),
    policy: PolicyPort = Depends(get_policy),
) -> ToolApprovalOut:
    governance = ToolGovernanceService(session, policy=policy)
    approval = await governance.request_tool_approval(
        organization_id=context.organization_id, workspace_id=context.workspace_id,
        tool_registration_id=body.tool_id, requested_by_user_id=current_user.id, payload=body.payload,
        destination=body.destination, cost=body.cost,
    )
    return ToolApprovalOut.model_validate(approval)


@router.get("/approvals", response_model=list[ToolApprovalOut])
async def list_pending_approvals(
    context: WorkspaceContext = Depends(get_workspace_context), session: AsyncSession = Depends(get_db_session)
) -> list[ToolApprovalOut]:
    repo = GovernanceRepository(session)
    approvals = await repo.list_pending_approvals_for_workspace(context.workspace_id)
    return [ToolApprovalOut.model_validate(a) for a in approvals]


@router.post("/approvals/{approval_id}/approve", response_model=ToolApprovalOut)
async def approve_tool_approval(
    approval_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    context: WorkspaceContext = Depends(get_workspace_context),
    session: AsyncSession = Depends(get_db_session),
    policy: PolicyPort = Depends(get_policy),
) -> ToolApprovalOut:
    repo = GovernanceRepository(session)
    existing = await repo.get_tool_approval_by_id(approval_id)
    if existing is None or existing.workspace_id != context.workspace_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Tool approval not found")

    governance = ToolGovernanceService(session, policy=policy)
    try:
        approval = await governance.approve_tool_approval(approval_id, approved_by_user_id=current_user.id)
    except ApprovalNotFound as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Tool approval not found") from exc
    return ToolApprovalOut.model_validate(approval)


@router.get("/audit-trail", response_model=list[AuditEventOut])
async def get_audit_trail_for_correlation_id(
    correlation_id: str = Query(...),
    session: AsyncSession = Depends(get_db_session),
) -> list[AuditEventOut]:
    """The exit-criterion query: pass the X-Correlation-Id you got back
    from any earlier response, and see every step that business action
    took — MCP tool authorization, OPA decision, application action —
    as one ordered trail."""
    repo = GovernanceRepository(session)
    events = await repo.list_events_for_correlation_id(correlation_id)
    return [AuditEventOut.model_validate(e) for e in events]


@router.post("/tools/generate-product-campaign/call", response_model=ToolCallResultOut)
async def call_generate_product_campaign(
    body: CallGenerateProductCampaignRequest,
    current_user: User = Depends(get_current_user),
    context: WorkspaceContext = Depends(get_workspace_context),
    session: AsyncSession = Depends(get_db_session),
    policy: PolicyPort = Depends(get_policy),
    secrets: SecretsPort = Depends(get_secrets),
) -> ToolCallResultOut:
    agent_context = AgentContext(
        organization_id=context.organization_id, workspace_id=context.workspace_id, user_id=current_user.id
    )
    server = build_agent_mcp_server(
        context=agent_context, session=session, policy=policy, secrets=secrets, store_adapter_factory=get_store_adapter,
    )
    call_result = await server.call_tool(
        "generate_product_campaign",
        {
            "product_id": str(body.product_id), "goal_slug": body.goal_slug, "mode": body.mode,
            "target_platforms": body.target_platforms,
        },
    )
    result = _structured_result(call_result)
    return ToolCallResultOut(authorized=bool(result.get("authorized", False)), result=result)


@router.post("/tools/generate-best-posting-time/call", response_model=ToolCallResultOut)
async def call_generate_best_posting_time(
    body: CallGenerateBestPostingTimeRequest,
    current_user: User = Depends(get_current_user),
    context: WorkspaceContext = Depends(get_workspace_context),
    session: AsyncSession = Depends(get_db_session),
    policy: PolicyPort = Depends(get_policy),
    secrets: SecretsPort = Depends(get_secrets),
) -> ToolCallResultOut:
    agent_context = AgentContext(
        organization_id=context.organization_id, workspace_id=context.workspace_id, user_id=current_user.id
    )
    server = build_agent_mcp_server(
        context=agent_context, session=session, policy=policy, secrets=secrets, store_adapter_factory=get_store_adapter,
    )
    call_result = await server.call_tool(
        "generate_best_posting_time",
        {"metric_name": body.metric_name, "data_window_days": body.data_window_days},
    )
    result = _structured_result(call_result)
    return ToolCallResultOut(authorized=bool(result.get("authorized", False)), result=result)
