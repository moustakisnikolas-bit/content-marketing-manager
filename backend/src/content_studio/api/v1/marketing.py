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
from content_studio.api.v1.content import _dispatch_generation_job
from content_studio.config import get_settings
from content_studio.correlation import get_correlation_id
from content_studio.modules.analytics.recommendation_engine import RecommendationEngine
from content_studio.modules.commerce.repository import CommerceRepository
from content_studio.modules.commerce.service import (
    build_story_brief,
    derive_story_hook,
    prepare_paired_image_generation,
    prepare_story_image_generation,
)
from content_studio.modules.creation.models import GenerationJob
from content_studio.modules.creation.repository import CreationRepository
from content_studio.modules.identity.models import User
from content_studio.modules.marketing.exceptions import MarketingError
from content_studio.modules.marketing.models import Campaign, CampaignPlanItem
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
    PublishApprovedResponse,
    PublishedProductOut,
    SkippedProductOut,
)
from content_studio.modules.marketing.service import MarketingService
from content_studio.modules.publishing.repository import PublishingRepository
from content_studio.workflows.autopilot import AutoPilotCampaignWorkflow
from content_studio.workflows.generation import GenerationWorkflow, GenerationWorkflowInput
from content_studio.workflows.publication import PublicationWorkflow, PublicationWorkflowInput

router = APIRouter(prefix="/marketing", tags=["marketing"])


async def _approved_job(creation_repo: CreationRepository, item: CampaignPlanItem | None) -> GenerationJob | None:
    if item is None or item.generation_job_id is None:
        return None
    job = await creation_repo.get_generation_job_by_id(item.generation_job_id)
    return job if job is not None and job.status == "approved" else None


async def _selected_revision(creation_repo: CreationRepository, content_item_id: uuid.UUID | None):
    if content_item_id is None:
        return None
    package = await creation_repo.get_package_for_item(content_item_id)
    if package is None:
        return None
    return await creation_repo.get_revision_by_id(package.selected_revision_id)


async def _maybe_create_companion_story(
    *,
    session: AsyncSession,
    marketing_repo: MarketingRepository,
    creation_repo: CreationRepository,
    temporal: Client,
    campaign: Campaign,
    current_user: User,
    subscription_id: uuid.UUID,
    image_item: CampaignPlanItem,
    caption_text: str | None,
    sequence_number: int,
) -> uuid.UUID | None:
    """Auto-generates a Story companion for a product's newly-scheduled
    Instagram post (see publish_approved() below). Dispatched immediately
    so it lands as an ordinary awaiting_review item in the same campaign —
    reusing the existing review panel is the whole point, no new approval
    UI surface needed. Approving it later publishes it via
    _maybe_publish_approved_story() in api/v1/content.py. Best-effort: any
    failure here must never undo or block the post that was actually just
    published."""
    if image_item.product_id is None:
        return None
    try:
        commerce_repo = CommerceRepository(session)
        product = await commerce_repo.get_product_with_details_by_id(image_item.product_id)
        if product is None:
            return None
        reference_image_url = min(product.assets, key=lambda a: a.position).url if product.assets else None
        hook_text = derive_story_hook(caption_text or product.title)
        brief_text = build_story_brief(product, hook_text)

        story_item = await marketing_repo.create_plan_item(
            campaign_id=image_item.campaign_id, sequence_number=sequence_number, title=f"{product.title} (story)",
            brief_text=brief_text, target_platform="instagram", product_id=product.id, content_type="story",
            source_plan_item_id=image_item.id,
        )
        prepared = await prepare_story_image_generation(session, story_item, reference_image_url=reference_image_url)
        if prepared is None:
            return story_item.id

        new_job = await _dispatch_generation_job(
            repo=creation_repo, session=session, temporal=temporal,
            organization_id=campaign.organization_id, workspace_id=campaign.workspace_id,
            content_item_id=prepared.content_item_id, recipe_id=prepared.recipe_id,
            requested_by_user_id=current_user.id, subscription_id=subscription_id,
            brief_text=prepared.brief_text, reference_image_url=prepared.reference_image_url,
        )
        await marketing_repo.link_plan_item_generation(
            story_item, content_item_id=prepared.content_item_id, generation_job_id=new_job.id
        )
        await marketing_repo.update_plan_item_status(story_item, "generating")
        await marketing_repo.update_plan_item_brief_text(story_item, prepared.brief_text)
        await session.commit()
        return story_item.id
    except Exception:  # noqa: BLE001 — the already-published post must not be undone by a story-side failure
        return None


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


@router.post("/campaigns/{campaign_id}/cancel", response_model=CampaignOut)
async def cancel_campaign(
    campaign_id: uuid.UUID,
    context: WorkspaceContext = Depends(get_workspace_context),
    session: AsyncSession = Depends(get_db_session),
) -> CampaignOut:
    """Soft-removes a campaign by reusing the existing "cancelled" status
    (already a valid CAMPAIGN_STATUSES value) rather than deleting rows —
    same reasoning as remove_plan_item() below: already-spent generation
    cost and history stay in the audit trail. Cancelled campaigns are
    filtered out of the default list on the frontend, not deleted."""
    repo = MarketingRepository(session)
    campaign = await repo.get_campaign_by_id(campaign_id)
    if campaign is None or campaign.workspace_id != context.workspace_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Campaign not found")
    if campaign.status == "cancelled":
        raise HTTPException(status.HTTP_409_CONFLICT, "Campaign is already cancelled")

    await repo.update_campaign_status(campaign, "cancelled")
    await session.commit()
    return CampaignOut.model_validate(campaign)


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
    creation_repo = CreationRepository(session)
    campaign = await marketing_repo.get_campaign_by_id(campaign_id)
    if campaign is None or campaign.workspace_id != context.workspace_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Campaign not found")
    plan_item = await marketing_repo.get_plan_item_by_id(item_id)
    if plan_item is None or plan_item.campaign_id != campaign_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Plan item not found")
    if plan_item.status != "pending":
        raise HTTPException(status.HTTP_409_CONFLICT, f"Item is not pending (status={plan_item.status})")

    if plan_item.content_type == "image" and plan_item.product_id is not None:
        # Bulk product-campaign image items are gated behind their paired
        # text item's approval — see prepare_paired_image_generation()'s
        # docstring for why (a real product photo, resolved fresh, not
        # whatever was known when the campaign was first built).
        siblings = await marketing_repo.list_plan_items_for_campaign(campaign_id)
        text_sibling = next(
            (
                i
                for i in siblings
                if i.product_id == plan_item.product_id
                and i.content_type == "text"
                # Match the same-platform pair only — a product can have one
                # pair per target platform (see build_bulk_plan_items).
                and i.target_platform == plan_item.target_platform
            ),
            None,
        )
        text_job = (
            await creation_repo.get_generation_job_by_id(text_sibling.generation_job_id)
            if text_sibling is not None and text_sibling.generation_job_id is not None
            else None
        )
        if text_job is None or text_job.status != "approved":
            raise HTTPException(status.HTTP_409_CONFLICT, "This image can't start until its text is approved")
        prepared = await prepare_paired_image_generation(session, plan_item)
        if prepared is None:
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_ENTITY, "Couldn't prepare this image (missing product or recipe)"
            )
    else:
        prepared = await MarketingService(session).prepare_item_generation(plan_item)

    job = await creation_repo.create_generation_job(
        organization_id=context.organization_id,
        workspace_id=context.workspace_id,
        content_item_id=prepared.content_item_id,
        recipe_id=prepared.recipe_id,
        requested_by_user_id=current_user.id,
        subscription_id=context.subscription_id,
        brief_text=prepared.brief_text,
        reference_image_url=prepared.reference_image_url,
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
    await marketing_repo.update_plan_item_brief_text(plan_item, prepared.brief_text)
    await session.commit()

    return {"status": "started", "job_id": str(job.id)}


@router.post("/campaigns/{campaign_id}/items/{item_id}/remove", status_code=status.HTTP_202_ACCEPTED)
async def remove_plan_item(
    campaign_id: uuid.UUID,
    item_id: uuid.UUID,
    context: WorkspaceContext = Depends(get_workspace_context),
    session: AsyncSession = Depends(get_db_session),
) -> dict[str, str]:
    """Soft-removes a product's item from a campaign by reusing the
    existing "cancelled" status, rather than deleting the row — keeps any
    already-spent generation cost in the audit trail, same reasoning as
    every other status transition in this module."""
    repo = MarketingRepository(session)
    campaign = await repo.get_campaign_by_id(campaign_id)
    if campaign is None or campaign.workspace_id != context.workspace_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Campaign not found")
    plan_item = await repo.get_plan_item_by_id(item_id)
    if plan_item is None or plan_item.campaign_id != campaign_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Plan item not found")
    if plan_item.status == "cancelled":
        raise HTTPException(status.HTTP_409_CONFLICT, "Item is already removed")

    await repo.update_plan_item_status(plan_item, "cancelled")
    await session.commit()
    return {"status": "cancelled"}


@router.post("/campaigns/{campaign_id}/publish-approved", response_model=PublishApprovedResponse)
async def publish_approved(
    campaign_id: uuid.UUID,
    dry_run: bool = False,
    current_user: User = Depends(get_current_user),
    context: WorkspaceContext = Depends(get_workspace_context),
    session: AsyncSession = Depends(get_db_session),
    temporal: Client = Depends(get_temporal_client_dep),
) -> PublishApprovedResponse:
    """Bulk-publishes every product in this campaign whose content is
    content-approved (GenerationJob.status == "approved") — closes the
    "campaigns don't launch on Instagram" gap: previously the only way to
    publish anything was the disconnected per-item form on /calendar,
    which nobody had ever pointed at Instagram. For a product with both an
    approved text and image item, copies the caption onto the image so
    the real post carries real text, then publishes the image (a
    text-only product with no paired image publishes its text directly,
    unchanged from before). Schedules each post on this workspace's own
    best-performing time (RecommendationEngine.suggest_next_scheduling_slots,
    one slot per day so a bulk publish doesn't blast everything out at
    once), self-approves the PublicationPlan it creates (the explicit
    "Publish approved" click IS the approval — same pattern as the
    paired-image auto-dispatch), and — for an Instagram post — also
    creates a companion Story plan item for its own separate review.

    dry_run=True runs the exact same grouping/validation/scheduling logic
    (so the returned scheduled_for times are the real times a live call
    would use) but performs none of the writes below — no PublicationPlan,
    no workflow, no caption copy, no Story — so the frontend can show the
    user what's about to happen before they commit to it."""
    marketing_repo = MarketingRepository(session)
    creation_repo = CreationRepository(session)
    publishing_repo = PublishingRepository(session)

    campaign = await marketing_repo.get_campaign_by_id(campaign_id)
    if campaign is None or campaign.workspace_id != context.workspace_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Campaign not found")

    items = await marketing_repo.list_plan_items_for_campaign(campaign_id)
    # Keyed by (product_id, target_platform), not just product_id — a
    # product can have one text+image pair per target platform (see
    # build_bulk_plan_items), and keying on product_id alone would let a
    # second platform's items silently overwrite the first's in this dict.
    products: dict[tuple[uuid.UUID, str | None], dict[str, CampaignPlanItem]] = {}
    for item in items:
        if item.product_id is None or item.status == "cancelled" or item.content_type == "story":
            continue
        products.setdefault((item.product_id, item.target_platform), {})[item.content_type] = item

    connections = await publishing_repo.list_connections_for_workspace(context.workspace_id)
    connections_by_platform = {c.platform: c for c in connections if c.status == "connected"}

    groups = list(products.items())
    slots = (
        await RecommendationEngine(session).suggest_next_scheduling_slots(
            organization_id=context.organization_id, workspace_id=context.workspace_id, count=len(groups)
        )
        if groups
        else []
    )
    slot_iter = iter(slots)
    next_sequence_number = len(items) + 1

    published: list[PublishedProductOut] = []
    skipped: list[SkippedProductOut] = []

    for (product_id, _target_platform), by_type in groups:
        text_item = by_type.get("text")
        image_item = by_type.get("image")
        text_job = await _approved_job(creation_repo, text_item)
        image_job = await _approved_job(creation_repo, image_item)

        if image_item is not None:
            if image_job is None:
                skipped.append(
                    SkippedProductOut(product_id=product_id, plan_item_id=image_item.id, reason="Image not approved yet")
                )
                continue
            primary_item = image_item
        elif text_item is not None:
            if text_job is None:
                skipped.append(
                    SkippedProductOut(product_id=product_id, plan_item_id=text_item.id, reason="Text not approved yet")
                )
                continue
            primary_item = text_item
        else:
            continue

        if primary_item.publication_plan_id is not None:
            skipped.append(SkippedProductOut(product_id=product_id, plan_item_id=primary_item.id, reason="Already published"))
            continue
        if primary_item.target_platform is None:
            skipped.append(SkippedProductOut(product_id=product_id, plan_item_id=primary_item.id, reason="No target platform set"))
            continue
        connection = connections_by_platform.get(primary_item.target_platform)
        if connection is None:
            skipped.append(
                SkippedProductOut(
                    product_id=product_id, plan_item_id=primary_item.id,
                    reason=f"No connected {primary_item.target_platform} account",
                )
            )
            continue

        will_create_story = primary_item is image_item and connection.platform == "instagram"
        caption_text: str | None = None
        if primary_item is image_item and text_job is not None and text_item is not None:
            text_revision = await _selected_revision(creation_repo, text_item.content_item_id)
            image_revision = await _selected_revision(creation_repo, image_item.content_item_id)
            if text_revision is not None and text_revision.text_body and image_revision is not None:
                caption_text = text_revision.text_body
                if not dry_run:
                    await creation_repo.update_revision_text(image_revision, caption_text)

        scheduled_for = next(slot_iter)
        plan_id: uuid.UUID | None = None
        story_item_id: uuid.UUID | None = None

        if not dry_run:
            plan = await publishing_repo.create_publication_plan(
                organization_id=context.organization_id, workspace_id=context.workspace_id,
                content_item_id=primary_item.content_item_id, platform_connection_id=connection.id,
                created_by_user_id=current_user.id, scheduled_for=scheduled_for, target_format="post",
            )
            await session.commit()
            plan_id = plan.id

            settings = get_settings()
            workflow_id = f"publication-{plan.id}"
            workflow_input = PublicationWorkflowInput(plan_id=str(plan.id), correlation_id=get_correlation_id())
            await temporal.start_workflow(
                PublicationWorkflow.run, args=[workflow_input, scheduled_for.isoformat()],
                id=workflow_id, task_queue=settings.temporal_task_queue,
            )
            await publishing_repo.set_plan_workflow_id(plan, workflow_id)
            await session.commit()

            handle = temporal.get_workflow_handle(workflow_id)
            try:
                await handle.signal(
                    PublicationWorkflow.submit_review,
                    args=["approved", str(current_user.id), "Auto-approved via bulk publish"],
                )
            except RPCError as exc:
                # The workflow may already have failed its capability check
                # (and completed) before this signal arrives — the plan's own
                # status already reflects that, so this isn't worth a 500.
                if exc.status != RPCStatusCode.NOT_FOUND:
                    raise

            await marketing_repo.link_plan_item_publication(primary_item, publication_plan_id=plan.id)

            if will_create_story:
                story_item_id = await _maybe_create_companion_story(
                    session=session, marketing_repo=marketing_repo, creation_repo=creation_repo, temporal=temporal,
                    campaign=campaign, current_user=current_user, subscription_id=context.subscription_id,
                    image_item=image_item, caption_text=caption_text, sequence_number=next_sequence_number,
                )
                next_sequence_number += 1

        published.append(
            PublishedProductOut(
                product_id=product_id, plan_item_id=primary_item.id, publication_plan_id=plan_id,
                scheduled_for=scheduled_for, story_plan_item_id=story_item_id, will_create_story=will_create_story,
            )
        )

    return PublishApprovedResponse(dry_run=dry_run, published=published, skipped=skipped)


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
    # TEMPORARY: Auto-Pilot is disabled workspace-wide. AutoPilotService.run_item()
    # hardcodes content_type="text" regardless of the plan item's actual
    # content_type, so an "image" item gets generated and published as a
    # nonsense text post instead of an image — confirmed live, already
    # published wrong content before this was caught. Remove this block
    # once run_item() is fixed to branch on plan_item.content_type the
    # same way the manual/guided dispatch paths already do.
    raise HTTPException(
        status.HTTP_503_SERVICE_UNAVAILABLE,
        "Auto-Pilot is temporarily disabled while a content-type bug is being fixed "
        "(it was generating and publishing image items as text). Use manual review on "
        "/campaigns instead for now.",
    )


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
