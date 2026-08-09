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
from content_studio.modules.creation.repository import CreationRepository
from content_studio.modules.creation.schemas import (
    ContentItemDetailOut,
    ContentItemOut,
    ContentPackageOut,
    ContentRevisionOut,
    CreateBriefRequest,
    CreateBriefResponse,
    GenerationJobOut,
    ReviewRequest,
)
from content_studio.modules.identity.models import User
from content_studio.workflows.client import get_temporal_client
from content_studio.workflows.generation import GenerationWorkflow, GenerationWorkflowInput

router = APIRouter(prefix="/content", tags=["content"])


async def get_temporal_client_dep() -> Client:
    return await get_temporal_client()


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
    job = await repo.create_generation_job(
        organization_id=context.organization_id,
        workspace_id=context.workspace_id,
        content_item_id=item.id,
        recipe_id=recipe.id,
        requested_by_user_id=current_user.id,
        subscription_id=context.subscription_id,
        brief_text=body.brief_text,
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
) -> dict[str, str]:
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
    return {"status": "signal_sent"}
