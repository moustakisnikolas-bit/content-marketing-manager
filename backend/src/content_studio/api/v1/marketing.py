import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from temporalio.client import Client
from temporalio.service import RPCError, RPCStatusCode

from content_studio.api.deps import (
    WorkspaceContext,
    get_current_user,
    get_db_session,
    get_temporal_client_dep,
    get_workspace_context,
)
from content_studio.config import get_settings
from content_studio.modules.creation.repository import CreationRepository
from content_studio.modules.identity.models import User
from content_studio.modules.marketing.exceptions import MarketingError
from content_studio.modules.marketing.repository import MarketingRepository
from content_studio.modules.marketing.schemas import (
    ApproveProposalRequest,
    ApproveProposalResponse,
    AutoPilotPolicyOut,
    CampaignDecisionOut,
    CampaignDetailOut,
    CampaignOut,
    CampaignPlanItemOut,
    CampaignProposalOut,
    CreateAutoPilotPolicyRequest,
    CreateBriefRequest,
    CreateBriefResponse,
    MarketingGoalOut,
)
from content_studio.modules.marketing.service import MarketingService
from content_studio.workflows.autopilot import AutoPilotCampaignWorkflow, AutoPilotWorkflowInput
from content_studio.workflows.generation import GenerationWorkflow, GenerationWorkflowInput

router = APIRouter(prefix="/marketing", tags=["marketing"])


@router.get("/goals", response_model=list[MarketingGoalOut])
async def list_goals(session: AsyncSession = Depends(get_db_session)) -> list[MarketingGoalOut]:
    repo = MarketingRepository(session)
    goals = await repo.list_goals()
    return [MarketingGoalOut.model_validate(g) for g in goals]


@router.post("/briefs", response_model=CreateBriefResponse, status_code=status.HTTP_201_CREATED)
async def create_brief(
    body: CreateBriefRequest,
    current_user: User = Depends(get_current_user),
    context: WorkspaceContext = Depends(get_workspace_context),
    session: AsyncSession = Depends(get_db_session),
) -> CreateBriefResponse:
    service = MarketingService(session)
    try:
        brief = await service.create_brief(
            organization_id=context.organization_id,
            workspace_id=context.workspace_id,
            user_id=current_user.id,
            goal_slug=body.goal_slug,
            what_to_promote=body.what_to_promote,
            mode=body.mode,
            target_platforms=body.target_platforms,
        )
        proposal = await service.generate_proposal(brief.id)
    except MarketingError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc)) from exc

    return CreateBriefResponse(brief_id=brief.id, proposal=CampaignProposalOut.model_validate(proposal))


@router.get("/proposals/{proposal_id}", response_model=CampaignProposalOut)
async def get_proposal(
    proposal_id: uuid.UUID,
    context: WorkspaceContext = Depends(get_workspace_context),
    session: AsyncSession = Depends(get_db_session),
) -> CampaignProposalOut:
    repo = MarketingRepository(session)
    proposal = await repo.get_proposal_by_id(proposal_id)
    if proposal is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Proposal not found")
    brief = await repo.get_brief_by_id(proposal.brief_id)
    if brief is None or brief.workspace_id != context.workspace_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Proposal not found")
    return CampaignProposalOut.model_validate(proposal)


@router.post("/proposals/{proposal_id}/approve", response_model=ApproveProposalResponse)
async def approve_proposal(
    proposal_id: uuid.UUID,
    body: ApproveProposalRequest,
    current_user: User = Depends(get_current_user),
    context: WorkspaceContext = Depends(get_workspace_context),
    session: AsyncSession = Depends(get_db_session),
) -> ApproveProposalResponse:
    repo = MarketingRepository(session)
    proposal = await repo.get_proposal_by_id(proposal_id)
    if proposal is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Proposal not found")
    brief = await repo.get_brief_by_id(proposal.brief_id)
    if brief is None or brief.workspace_id != context.workspace_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Proposal not found")

    service = MarketingService(session)
    campaign = await service.approve_proposal(
        proposal_id=proposal_id, user_id=current_user.id, campaign_name=body.campaign_name
    )
    return ApproveProposalResponse(campaign_id=campaign.id)


@router.get("/campaigns", response_model=list[CampaignOut])
async def list_campaigns(
    context: WorkspaceContext = Depends(get_workspace_context),
    session: AsyncSession = Depends(get_db_session),
) -> list[CampaignOut]:
    repo = MarketingRepository(session)
    campaigns = await repo.list_campaigns_for_workspace(context.workspace_id)
    return [CampaignOut.model_validate(c) for c in campaigns]


@router.get("/campaigns/{campaign_id}", response_model=CampaignDetailOut)
async def get_campaign(
    campaign_id: uuid.UUID,
    context: WorkspaceContext = Depends(get_workspace_context),
    session: AsyncSession = Depends(get_db_session),
) -> CampaignDetailOut:
    repo = MarketingRepository(session)
    campaign = await repo.get_campaign_by_id(campaign_id)
    if campaign is None or campaign.workspace_id != context.workspace_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Campaign not found")
    items = await repo.list_plan_items_for_campaign(campaign_id)
    decisions = await repo.list_decisions_for_campaign(campaign_id)

    # Reads through to each "generating" item's real GenerationJob state —
    # that stored status is written once at dispatch and never updated
    # again outside Auto-Pilot's own path, so it can be stale. See
    # MarketingService.get_effective_plan_item_statuses().
    effective_statuses = await MarketingService(session).get_effective_plan_item_statuses(items)
    plan_items_out = []
    for item in items:
        item_out = CampaignPlanItemOut.model_validate(item)
        item_out.status = effective_statuses[item.id]
        plan_items_out.append(item_out)

    return CampaignDetailOut(
        campaign=CampaignOut.model_validate(campaign),
        plan_items=plan_items_out,
        decisions=[CampaignDecisionOut.model_validate(d) for d in decisions],
    )


@router.post("/campaigns/{campaign_id}/items/{item_id}/start", status_code=status.HTTP_202_ACCEPTED)
async def start_plan_item(
    campaign_id: uuid.UUID,
    item_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    context: WorkspaceContext = Depends(get_workspace_context),
    session: AsyncSession = Depends(get_db_session),
    temporal: Client = Depends(get_temporal_client_dep),
) -> dict[str, str]:
    """Manual/Guided dispatch: starts the same GenerationWorkflow Phase 2's
    Create Content page uses — a campaign just orchestrates existing
    infrastructure, it doesn't reimplement it."""
    marketing_repo = MarketingRepository(session)
    campaign = await marketing_repo.get_campaign_by_id(campaign_id)
    if campaign is None or campaign.workspace_id != context.workspace_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Campaign not found")
    plan_item = await marketing_repo.get_plan_item_by_id(item_id)
    if plan_item is None or plan_item.campaign_id != campaign_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Plan item not found")
    if plan_item.status != "pending":
        raise HTTPException(status.HTTP_409_CONFLICT, f"Item is not pending (status={plan_item.status})")

    service = MarketingService(session)
    prepared = await service.prepare_item_generation(plan_item)

    creation_repo = CreationRepository(session)
    job = await creation_repo.create_generation_job(
        organization_id=context.organization_id,
        workspace_id=context.workspace_id,
        content_item_id=prepared.content_item_id,
        recipe_id=prepared.recipe_id,
        requested_by_user_id=current_user.id,
        subscription_id=context.subscription_id,
        brief_text=prepared.brief_text,
    )
    await session.commit()

    settings = get_settings()
    workflow_id = f"generation-{job.id}"
    await temporal.start_workflow(
        GenerationWorkflow.run,
        GenerationWorkflowInput(job_id=str(job.id)),
        id=workflow_id,
        task_queue=settings.temporal_task_queue,
    )
    await creation_repo.set_job_workflow_id(job, workflow_id)
    await marketing_repo.link_plan_item_generation(plan_item, content_item_id=prepared.content_item_id, generation_job_id=job.id)
    await marketing_repo.update_plan_item_status(plan_item, "generating")
    await session.commit()

    return {"status": "started", "job_id": str(job.id)}


@router.post("/campaigns/{campaign_id}/autopilot-policy", response_model=AutoPilotPolicyOut, status_code=status.HTTP_201_CREATED)
async def create_autopilot_policy(
    campaign_id: uuid.UUID,
    body: CreateAutoPilotPolicyRequest,
    current_user: User = Depends(get_current_user),
    context: WorkspaceContext = Depends(get_workspace_context),
    session: AsyncSession = Depends(get_db_session),
) -> AutoPilotPolicyOut:
    repo = MarketingRepository(session)
    campaign = await repo.get_campaign_by_id(campaign_id)
    if campaign is None or campaign.workspace_id != context.workspace_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Campaign not found")

    policy = await repo.create_autopilot_policy(
        campaign_id=campaign_id,
        created_by_user_id=current_user.id,
        allowed_platforms=body.allowed_platforms,
        max_total_spend=body.max_total_spend,
        blocked_topics=body.blocked_topics,
        posting_window_start_hour=body.posting_window_start_hour,
        posting_window_end_hour=body.posting_window_end_hour,
    )
    await session.commit()
    return AutoPilotPolicyOut.model_validate(policy)


@router.get("/campaigns/{campaign_id}/autopilot-policy", response_model=AutoPilotPolicyOut)
async def get_autopilot_policy(
    campaign_id: uuid.UUID,
    context: WorkspaceContext = Depends(get_workspace_context),
    session: AsyncSession = Depends(get_db_session),
) -> AutoPilotPolicyOut:
    repo = MarketingRepository(session)
    campaign = await repo.get_campaign_by_id(campaign_id)
    if campaign is None or campaign.workspace_id != context.workspace_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Campaign not found")
    policy = await repo.get_autopilot_policy_for_campaign(campaign_id)
    if policy is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No Auto-Pilot policy configured for this campaign")
    return AutoPilotPolicyOut.model_validate(policy)


@router.post("/campaigns/{campaign_id}/autopilot/start", status_code=status.HTTP_202_ACCEPTED)
async def start_autopilot(
    campaign_id: uuid.UUID,
    context: WorkspaceContext = Depends(get_workspace_context),
    session: AsyncSession = Depends(get_db_session),
    temporal: Client = Depends(get_temporal_client_dep),
) -> dict[str, str]:
    repo = MarketingRepository(session)
    campaign = await repo.get_campaign_by_id(campaign_id)
    if campaign is None or campaign.workspace_id != context.workspace_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Campaign not found")
    policy = await repo.get_autopilot_policy_for_campaign(campaign_id)
    if policy is None:
        raise HTTPException(status.HTTP_409_CONFLICT, "Configure an Auto-Pilot policy before starting")

    items = await repo.list_plan_items_for_campaign(campaign_id)
    pending_item_ids = [str(i.id) for i in items if i.status == "pending"]
    if not pending_item_ids:
        raise HTTPException(status.HTTP_409_CONFLICT, "No pending items to run")

    settings = get_settings()
    workflow_id = f"autopilot-{campaign_id}"
    await temporal.start_workflow(
        AutoPilotCampaignWorkflow.run,
        AutoPilotWorkflowInput(campaign_id=str(campaign_id), plan_item_ids=pending_item_ids),
        id=workflow_id,
        task_queue=settings.temporal_task_queue,
    )
    await repo.set_campaign_workflow_id(campaign, workflow_id)
    await repo.update_campaign_status(campaign, "active")
    await session.commit()
    return {"status": "started", "workflow_id": workflow_id}


@router.post("/campaigns/{campaign_id}/autopilot/halt", status_code=status.HTTP_202_ACCEPTED)
async def halt_autopilot(
    campaign_id: uuid.UUID,
    context: WorkspaceContext = Depends(get_workspace_context),
    session: AsyncSession = Depends(get_db_session),
    temporal: Client = Depends(get_temporal_client_dep),
) -> dict[str, str]:
    """The kill switch. Sets the DB flag (caught by the OPA guardrail check
    before the next item regardless) and sends an explicit signal to the
    running workflow for an immediate stop, rather than waiting for the
    next item boundary."""
    repo = MarketingRepository(session)
    campaign = await repo.get_campaign_by_id(campaign_id)
    if campaign is None or campaign.workspace_id != context.workspace_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Campaign not found")
    policy = await repo.get_autopilot_policy_for_campaign(campaign_id)
    if policy is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No Auto-Pilot policy configured for this campaign")

    await repo.set_kill_switch(policy, True)
    await session.commit()

    if campaign.temporal_workflow_id:
        handle = temporal.get_workflow_handle(campaign.temporal_workflow_id)
        try:
            await handle.signal(AutoPilotCampaignWorkflow.halt)
        except RPCError as exc:
            # The workflow may have already finished all its items (or
            # failed) before the signal arrives — the kill switch DB flag
            # is set regardless, which is what stops any *future* run, so
            # this isn't an error condition worth a 500.
            if exc.status != RPCStatusCode.NOT_FOUND:
                raise

    return {"status": "halted"}


@router.get("/campaigns/{campaign_id}/decisions", response_model=list[CampaignDecisionOut])
async def list_decisions(
    campaign_id: uuid.UUID,
    context: WorkspaceContext = Depends(get_workspace_context),
    session: AsyncSession = Depends(get_db_session),
) -> list[CampaignDecisionOut]:
    repo = MarketingRepository(session)
    campaign = await repo.get_campaign_by_id(campaign_id)
    if campaign is None or campaign.workspace_id != context.workspace_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Campaign not found")
    decisions = await repo.list_decisions_for_campaign(campaign_id)
    return [CampaignDecisionOut.model_validate(d) for d in decisions]
