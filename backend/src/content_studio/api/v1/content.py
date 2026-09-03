import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from temporalio.client import Client

from content_studio.api.deps import (
    WorkspaceContext,
    get_current_user,
    get_db_session,
    get_workspace_context,
)
from content_studio.config import get_settings
from content_studio.correlation import get_correlation_id
from content_studio.modules.commerce.service import prepare_paired_image_generation
from content_studio.modules.creation.models import GenerationJob
from content_studio.modules.creation.repository import CreationRepository
from content_studio.modules.creation.schemas import (
    ContentItemDetailOut,
    ContentItemOut,
    ContentPackageOut,
    ContentRevisionOut,
    CreateBriefRequest,
    CreateBriefResponse,
    EditRevisionTextRequest,
    EditRevisionTextResponse,
    GenerationJobOut,
    RegenerateJobRequest,
    RegenerateJobResponse,
    ReviewRequest,
)
from content_studio.modules.creation.text_diff import extract_meaningful_deletions
from content_studio.modules.governance.service import AuditService
from content_studio.modules.identity.models import User
from content_studio.modules.marketing.repository import MarketingRepository
from content_studio.modules.publishing.repository import PublishingRepository
from content_studio.workflows.client import get_temporal_client
from content_studio.workflows.generation import GenerationWorkflow, GenerationWorkflowInput
from content_studio.workflows.publication import PublicationWorkflow, PublicationWorkflowInput

router = APIRouter(prefix="/content", tags=["content"])


async def get_temporal_client_dep() -> Client:
    return await get_temporal_client()


async def _dispatch_generation_job(
    *,
    repo: CreationRepository,
    session: AsyncSession,
    temporal: Client,
    organization_id: uuid.UUID,
    workspace_id: uuid.UUID,
    content_item_id: uuid.UUID,
    recipe_id: uuid.UUID,
    requested_by_user_id: uuid.UUID,
    subscription_id: uuid.UUID,
    brief_text: str,
    reference_image_url: str | None = None,
) -> GenerationJob:
    """Creates a GenerationJob and starts its GenerationWorkflow — the
    create-then-dispatch sequence shared by create_brief(), the
    reject-and-regenerate branch, and the auto-dispatch-paired-image branch
    of review_generation_job() below. Two commits: the job row must exist
    before Temporal can be told its id, and the workflow id must be
    persisted once Temporal accepts the start."""
    job = await repo.create_generation_job(
        organization_id=organization_id,
        workspace_id=workspace_id,
        content_item_id=content_item_id,
        recipe_id=recipe_id,
        requested_by_user_id=requested_by_user_id,
        subscription_id=subscription_id,
        brief_text=brief_text,
        reference_image_url=reference_image_url,
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
    await repo.set_job_workflow_id(job, workflow_id)
    await session.commit()
    return job


async def _maybe_dispatch_paired_image(
    job: GenerationJob, current_user: User, session: AsyncSession, temporal: Client
) -> None:
    """When an approved job is the TEXT half of a bulk product-campaign
    pair, dispatches its paired IMAGE plan item now instead of it having
    started immediately alongside the text (that used to happen, and
    produced images before anyone had approved the caption they went
    with). See prepare_paired_image_generation()'s docstring for why the
    product photo is re-resolved fresh here rather than reusing whatever
    was known at campaign-creation time. Best-effort: any failure here
    must never break the text approval itself — the image item is simply
    left "pending" for a manual retry."""
    try:
        marketing_repo = MarketingRepository(session)
        # A plain job_id lookup can now match more than one plan item (a
        # shared image job referenced by two platforms) — filter to the
        # "text" one specifically; a job that's actually a shared image
        # job will have none, which correctly no-ops this function via the
        # check below rather than crashing on an assumed single match.
        candidates = await marketing_repo.list_plan_items_by_generation_job_id(job.id)
        text_plan_item = next((i for i in candidates if i.content_type == "text"), None)
        if text_plan_item is None or text_plan_item.product_id is None:
            return
        siblings = await marketing_repo.list_plan_items_for_campaign(text_plan_item.campaign_id)
        image_item = next(
            (
                i
                for i in siblings
                if i.product_id == text_plan_item.product_id
                and i.content_type == "image"
                and i.status == "pending"
                # A product can have one pair per target platform (see
                # build_bulk_plan_items) — match same-platform siblings only,
                # or an Instagram text approval could dispatch the Facebook
                # image (or vice versa) while leaving its real pair stranded.
                and i.target_platform == text_plan_item.target_platform
            ),
            None,
        )
        if image_item is None:
            return

        # Don't generate a separate image per platform for the same
        # product — Facebook and Instagram should show the identical
        # photo, only the caption differs. If another platform's pair for
        # this same product already has a generated image, reuse it
        # directly instead of running AI image generation again (a second
        # independent call wouldn't reproduce an identical image even from
        # the same prompt/reference photo). Best-effort, not race-safe:
        # two platforms' texts approved within the same instant could both
        # still dispatch their own generation — acceptable given how
        # unlikely that is in practice.
        existing_image = next(
            (
                i
                for i in siblings
                if i.product_id == text_plan_item.product_id
                and i.content_type == "image"
                and i.id != image_item.id
                and i.content_item_id is not None
            ),
            None,
        )
        if existing_image is not None:
            await marketing_repo.link_plan_item_generation(
                image_item, content_item_id=existing_image.content_item_id,
                generation_job_id=existing_image.generation_job_id,
            )
            await marketing_repo.update_plan_item_status(image_item, "generating")
            await session.commit()
            return

        prepared = await prepare_paired_image_generation(session, image_item)
        if prepared is None:
            return

        repo = CreationRepository(session)
        new_job = await _dispatch_generation_job(
            repo=repo,
            session=session,
            temporal=temporal,
            organization_id=job.organization_id,
            workspace_id=job.workspace_id,
            content_item_id=prepared.content_item_id,
            recipe_id=prepared.recipe_id,
            requested_by_user_id=current_user.id,
            subscription_id=job.subscription_id,
            brief_text=prepared.brief_text,
            reference_image_url=prepared.reference_image_url,
        )
        await marketing_repo.link_plan_item_generation(
            image_item, content_item_id=prepared.content_item_id, generation_job_id=new_job.id
        )
        await marketing_repo.update_plan_item_status(image_item, "generating")
        await marketing_repo.update_plan_item_brief_text(image_item, prepared.brief_text)
        await session.commit()
    except Exception:  # noqa: BLE001, S110 — must never break the text-approval response itself
        pass


async def _maybe_publish_approved_story(
    job: GenerationJob, current_user: User, session: AsyncSession, temporal: Client
) -> None:
    """When an approved job is a companion Story item (created by
    publish_approved() in api/v1/marketing.py), immediately publishes it —
    same "the explicit Approve click IS the approval" pattern as
    _maybe_dispatch_paired_image() above, just a step later in the
    pipeline: a story publishes rather than cascading into dispatching
    anything else. scheduled_for is None (publish right away) since,
    unlike its parent post, a story isn't scheduled onto a best-time slot.
    Best-effort: any failure here must never break the approval response
    itself."""
    try:
        marketing_repo = MarketingRepository(session)
        # See the matching comment in _maybe_dispatch_paired_image() above —
        # a shared image job can match more than one plan item now.
        candidates = await marketing_repo.list_plan_items_by_generation_job_id(job.id)
        story_item = next((i for i in candidates if i.content_type == "story"), None)
        if story_item is None or story_item.publication_plan_id is not None:
            return

        publishing_repo = PublishingRepository(session)
        connections = await publishing_repo.list_connections_for_workspace(job.workspace_id)
        connection = next((c for c in connections if c.platform == "instagram" and c.status == "connected"), None)
        if connection is None:
            return

        plan = await publishing_repo.create_publication_plan(
            organization_id=job.organization_id, workspace_id=job.workspace_id,
            content_item_id=job.content_item_id, platform_connection_id=connection.id,
            created_by_user_id=current_user.id, scheduled_for=None, target_format="story",
        )
        await session.commit()

        settings = get_settings()
        workflow_id = f"publication-{plan.id}"
        workflow_input = PublicationWorkflowInput(plan_id=str(plan.id), correlation_id=get_correlation_id())
        await temporal.start_workflow(
            PublicationWorkflow.run, args=[workflow_input, None], id=workflow_id, task_queue=settings.temporal_task_queue,
        )
        await publishing_repo.set_plan_workflow_id(plan, workflow_id)
        await session.commit()

        handle = temporal.get_workflow_handle(workflow_id)
        await handle.signal(
            PublicationWorkflow.submit_review, args=["approved", str(current_user.id), "Auto-approved story"],
        )
        await marketing_repo.link_plan_item_publication(story_item, publication_plan_id=plan.id)
        await session.commit()
    except Exception:  # noqa: BLE001, S110 — must never break the approval response itself
        pass


@router.post("/briefs", response_model=CreateBriefResponse, status_code=status.HTTP_201_CREATED)
async def create_brief(
    body: CreateBriefRequest,
    current_user: User = Depends(get_current_user),
    context: WorkspaceContext = Depends(get_workspace_context),
    session: AsyncSession = Depends(get_db_session),
    temporal: Client = Depends(get_temporal_client_dep),
) -> CreateBriefResponse:
    repo = CreationRepository(session)

    recipe = await repo.get_active_recipe_for_content_type(body.content_type)
    if recipe is None:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY, f"No active recipe for content_type={body.content_type!r}"
        )

    item = await repo.create_content_item(
        organization_id=context.organization_id,
        workspace_id=context.workspace_id,
        created_by_user_id=current_user.id,
        content_type=body.content_type,
        title=body.title,
        brand_profile_id=body.brand_profile_id,
    )
    job = await _dispatch_generation_job(
        repo=repo,
        session=session,
        temporal=temporal,
        organization_id=context.organization_id,
        workspace_id=context.workspace_id,
        content_item_id=item.id,
        recipe_id=recipe.id,
        requested_by_user_id=current_user.id,
        subscription_id=context.subscription_id,
        brief_text=body.brief_text,
    )

    return CreateBriefResponse(content_item_id=item.id, job_id=job.id)


@router.get("/items", response_model=list[ContentItemOut])
async def list_content_items(
    context: WorkspaceContext = Depends(get_workspace_context),
    session: AsyncSession = Depends(get_db_session),
) -> list[ContentItemOut]:
    repo = CreationRepository(session)
    items = await repo.list_content_items_for_workspace(context.workspace_id)
    return [ContentItemOut.model_validate(i) for i in items]


@router.get("/items/{item_id}", response_model=ContentItemDetailOut)
async def get_content_item(
    item_id: uuid.UUID,
    context: WorkspaceContext = Depends(get_workspace_context),
    session: AsyncSession = Depends(get_db_session),
) -> ContentItemDetailOut:
    repo = CreationRepository(session)
    item = await repo.get_content_item_by_id(item_id)
    if item is None or item.workspace_id != context.workspace_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Content item not found")

    revisions = await repo.list_revisions_for_item(item_id)
    package = await repo.get_package_for_item(item_id)
    return ContentItemDetailOut(
        item=ContentItemOut.model_validate(item),
        revisions=[ContentRevisionOut.model_validate(r) for r in revisions],
        package=ContentPackageOut.model_validate(package) if package else None,
    )


@router.post("/revisions/{revision_id}/edit", response_model=EditRevisionTextResponse)
async def edit_revision_text(
    revision_id: uuid.UUID,
    body: EditRevisionTextRequest,
    current_user: User = Depends(get_current_user),
    context: WorkspaceContext = Depends(get_workspace_context),
    session: AsyncSession = Depends(get_db_session),
) -> EditRevisionTextResponse:
    """Lets a reviewer fix generated text directly instead of only
    Approve/Reject — a rejection burns a full regeneration for what might
    be a one-word fix. Diffs what was deleted (extract_meaningful_deletions)
    and, when this revision belongs to a bulk-campaign plan item, strips
    the same phrase from every sibling text item still awaiting review in
    the same campaign right now — the actual pain point being solved is
    not re-typing the same fix across a whole batch. Also persists each
    deletion as a TextEditLearning row so future generations avoid it too
    (see commerce/service.py's _build_text_brief)."""
    repo = CreationRepository(session)
    revision = await repo.get_revision_by_id(revision_id)
    if revision is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Revision not found")
    item = await repo.get_content_item_by_id(revision.content_item_id)
    if item is None or item.workspace_id != context.workspace_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Revision not found")
    if revision.text_body is None:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "This revision has no text to edit")

    deletions = extract_meaningful_deletions(revision.text_body, body.text_body)
    for deleted in deletions:
        await repo.create_text_edit_learning(
            organization_id=item.organization_id,
            workspace_id=item.workspace_id,
            source_content_revision_id=revision.id,
            deleted_text=deleted,
        )
    await repo.update_revision_text(revision, body.text_body)

    applied_to_siblings = 0
    marketing_repo = MarketingRepository(session)
    plan_item = await marketing_repo.get_plan_item_by_content_item_id(revision.content_item_id)
    if plan_item is not None and deletions:
        siblings = await marketing_repo.list_plan_items_for_campaign(plan_item.campaign_id)
        for sibling in siblings:
            if (
                sibling.id == plan_item.id
                or sibling.content_type != "text"
                or sibling.content_item_id is None
                or sibling.generation_job_id is None
            ):
                continue
            sibling_job = await repo.get_generation_job_by_id(sibling.generation_job_id)
            if sibling_job is None or sibling_job.status != "awaiting_review":
                continue
            sibling_revisions = await repo.list_revisions_for_item(sibling.content_item_id)
            if not sibling_revisions or sibling_revisions[-1].text_body is None:
                continue
            sibling_revision = sibling_revisions[-1]
            updated_text = sibling_revision.text_body
            for deleted in deletions:
                updated_text = updated_text.replace(deleted, "")
            if updated_text != sibling_revision.text_body:
                await repo.update_revision_text(sibling_revision, updated_text)
                applied_to_siblings += 1

    await AuditService(session).record(
        event_type="content.revision_edited",
        actor_type="user",
        actor_id=str(current_user.id),
        organization_id=item.organization_id,
        summary=(
            f"Edited '{item.title}'"
            + (f" — applied to {applied_to_siblings} other pending item(s)" if applied_to_siblings else "")
        ),
        payload={"revision_id": str(revision.id), "applied_to_siblings": applied_to_siblings},
    )
    await session.commit()

    return EditRevisionTextResponse(
        revision=ContentRevisionOut.model_validate(revision), applied_to_siblings=applied_to_siblings
    )


@router.get("/jobs", response_model=list[GenerationJobOut])
async def list_generation_jobs(
    context: WorkspaceContext = Depends(get_workspace_context),
    session: AsyncSession = Depends(get_db_session),
) -> list[GenerationJobOut]:
    repo = CreationRepository(session)
    jobs = await repo.list_generation_jobs_for_workspace(context.workspace_id)
    return [GenerationJobOut.model_validate(j) for j in jobs]


@router.get("/jobs/{job_id}", response_model=GenerationJobOut)
async def get_generation_job(
    job_id: uuid.UUID,
    context: WorkspaceContext = Depends(get_workspace_context),
    session: AsyncSession = Depends(get_db_session),
) -> GenerationJobOut:
    repo = CreationRepository(session)
    job = await repo.get_generation_job_by_id(job_id)
    if job is None or job.workspace_id != context.workspace_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Generation job not found")
    return GenerationJobOut.model_validate(job)


@router.post("/jobs/{job_id}/review", status_code=status.HTTP_202_ACCEPTED)
async def review_generation_job(
    job_id: uuid.UUID,
    body: ReviewRequest,
    current_user: User = Depends(get_current_user),
    context: WorkspaceContext = Depends(get_workspace_context),
    session: AsyncSession = Depends(get_db_session),
    temporal: Client = Depends(get_temporal_client_dep),
) -> dict[str, str | None]:
    repo = CreationRepository(session)
    job = await repo.get_generation_job_by_id(job_id)
    if job is None or job.workspace_id != context.workspace_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Generation job not found")
    if job.status != "awaiting_review":
        raise HTTPException(status.HTTP_409_CONFLICT, f"Job is not awaiting review (status={job.status})")
    if job.temporal_workflow_id is None:
        raise HTTPException(status.HTTP_409_CONFLICT, "Job has no workflow to signal")

    handle = temporal.get_workflow_handle(job.temporal_workflow_id)
    await handle.signal(
        GenerationWorkflow.submit_review,
        args=[body.decision, str(current_user.id), body.comment],
    )

    if body.decision == "approved":
        await _maybe_dispatch_paired_image(job, current_user, session, temporal)
        await _maybe_publish_approved_story(job, current_user, session, temporal)
        return {"status": "signal_sent", "new_job_id": None}

    new_brief_text = f"{job.brief_text}\n\nRevision requested: {body.comment}" if body.comment else job.brief_text
    new_job = await _dispatch_generation_job(
        repo=repo,
        session=session,
        temporal=temporal,
        organization_id=job.organization_id,
        workspace_id=job.workspace_id,
        content_item_id=job.content_item_id,
        recipe_id=job.recipe_id,
        requested_by_user_id=current_user.id,
        subscription_id=job.subscription_id,
        brief_text=new_brief_text,
        reference_image_url=job.reference_image_url,
    )

    marketing_repo = MarketingRepository(session)
    # Every plan item that referenced the rejected job — not just one.
    # An image shared across platforms (see list_plan_items_by_generation_job_id's
    # docstring) means rejecting it on one platform must re-point every
    # platform sharing it to the same regenerated job, so e.g. rejecting
    # Facebook's image also recreates Instagram's instead of leaving it
    # stuck referencing the rejected version.
    plan_items = await marketing_repo.list_plan_items_by_generation_job_id(job_id)
    for plan_item in plan_items:
        await marketing_repo.link_plan_item_generation(
            plan_item, content_item_id=job.content_item_id, generation_job_id=new_job.id
        )
    if plan_items:
        await session.commit()

    return {"status": "signal_sent", "new_job_id": str(new_job.id)}


@router.post("/jobs/{job_id}/regenerate", response_model=RegenerateJobResponse, status_code=status.HTTP_202_ACCEPTED)
async def regenerate_generation_job(
    job_id: uuid.UUID,
    body: RegenerateJobRequest,
    current_user: User = Depends(get_current_user),
    context: WorkspaceContext = Depends(get_workspace_context),
    session: AsyncSession = Depends(get_db_session),
    temporal: Client = Depends(get_temporal_client_dep),
) -> RegenerateJobResponse:
    """Dispatches a fresh generation from a freely-edited prompt — for
    iterating on an image's prompt (most useful there, since there's no
    way to hand-edit pixels the way edit_revision_text() lets you hand-edit
    text) before deciding whether to Approve or Reject the result.
    Deliberately NOT the same as rejecting: Reject records a final negative
    verdict and always appends "Revision requested: ..." onto the existing
    prompt rather than replacing it, which compounds into prompt bloat
    over repeated iterations; this replaces the prompt outright and
    doesn't touch the job's review status or signal its workflow — that
    workflow is simply left durably idle (harmless) once the plan item(s)
    move on to the new job, same as any superseded generation."""
    repo = CreationRepository(session)
    job = await repo.get_generation_job_by_id(job_id)
    if job is None or job.workspace_id != context.workspace_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Generation job not found")
    if job.status != "awaiting_review":
        raise HTTPException(status.HTTP_409_CONFLICT, f"Job is not awaiting review (status={job.status})")

    new_job = await _dispatch_generation_job(
        repo=repo,
        session=session,
        temporal=temporal,
        organization_id=job.organization_id,
        workspace_id=job.workspace_id,
        content_item_id=job.content_item_id,
        recipe_id=job.recipe_id,
        requested_by_user_id=current_user.id,
        subscription_id=job.subscription_id,
        brief_text=body.brief_text,
        reference_image_url=job.reference_image_url,
    )

    marketing_repo = MarketingRepository(session)
    # Same cascade as the reject branch above — a shared image's plan
    # items (one per platform) must all move to the new job together.
    plan_items = await marketing_repo.list_plan_items_by_generation_job_id(job_id)
    for plan_item in plan_items:
        await marketing_repo.link_plan_item_generation(
            plan_item, content_item_id=job.content_item_id, generation_job_id=new_job.id
        )
        await marketing_repo.update_plan_item_brief_text(plan_item, body.brief_text)
    if plan_items:
        await session.commit()

    return RegenerateJobResponse(new_job_id=new_job.id)
