import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from temporalio.client import Client

from content_studio.api.deps import (
    WorkspaceContext,
    get_current_user,
    get_db_session,
    get_object_storage,
    get_platform_adapter,
    get_secrets,
    get_workspace_context,
)
from content_studio.config import get_settings
from content_studio.correlation import get_correlation_id
from content_studio.modules.identity.models import User
from content_studio.modules.publishing.exceptions import InvalidOAuthState, PlatformDeleteRejected
from content_studio.modules.publishing.oauth_state import (
    create_oauth_state,
    create_pending_connection_token,
    decode_oauth_state,
    decode_pending_connection_token,
)
from content_studio.modules.publishing.repository import PublishingRepository
from content_studio.modules.publishing.schemas import (
    AuthorizationUrlOut,
    CapabilityOut,
    ConnectableAccountOut,
    ConnectionDetailOut,
    CreatePublicationPlanRequest,
    CreatePublicationPlanResponse,
    PendingPageSelectionOut,
    PlatformConnectionOut,
    PublicationAttemptDetailOut,
    PublicationAttemptOut,
    PublicationPlanOut,
    PublicationReviewRequest,
    ReconciliationOut,
    SelectPageRequest,
)
from content_studio.modules.publishing.service import PendingAccountSelection, PublishingService
from content_studio.ports.object_storage import ObjectStoragePort
from content_studio.ports.secrets import SecretsPort
from content_studio.workflows.client import get_temporal_client
from content_studio.workflows.publication import PublicationWorkflow, PublicationWorkflowInput

router = APIRouter(prefix="/publishing", tags=["publishing"])


async def get_temporal_client_dep() -> Client:
    return await get_temporal_client()


async def _connection_detail(repo: PublishingRepository, connection) -> ConnectionDetailOut:
    capabilities = await repo.list_capabilities_for_connection(connection.id)
    return ConnectionDetailOut(
        connection=PlatformConnectionOut.model_validate(connection),
        capabilities=[CapabilityOut.model_validate(c) for c in capabilities],
    )


@router.get("/oauth/authorize", response_model=AuthorizationUrlOut)
async def get_authorization_url(
    platform: str,
    current_user: User = Depends(get_current_user),
    context: WorkspaceContext = Depends(get_workspace_context),
) -> AuthorizationUrlOut:
    if platform not in ("facebook", "instagram", "tiktok", "youtube"):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, f"Unsupported platform {platform!r}")

    state = create_oauth_state(
        organization_id=context.organization_id,
        workspace_id=context.workspace_id,
        user_id=current_user.id,
        platform=platform,
    )
    adapter = get_platform_adapter(platform)
    return AuthorizationUrlOut(authorization_url=adapter.get_authorization_url(state=state))


@router.get("/oauth/callback", response_model=ConnectionDetailOut | PendingPageSelectionOut)
async def oauth_callback(
    code: str,
    state: str,
    session: AsyncSession = Depends(get_db_session),
    secrets: SecretsPort = Depends(get_secrets),
    object_storage: ObjectStoragePort = Depends(get_object_storage),
) -> ConnectionDetailOut | PendingPageSelectionOut:
    """No Bearer auth here — a platform's OAuth redirect can't carry our
    Authorization header, so the signed `state` param is the only carrier
    of who's connecting what. See oauth_state.py.

    Returns PendingPageSelectionOut instead of ConnectionDetailOut when the
    exchanged token could publish as more than one account (Meta: multiple
    Facebook Pages) — the frontend must then show a picker and POST the
    choice to /oauth/select-page."""
    try:
        claims = decode_oauth_state(state)
    except InvalidOAuthState as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc

    organization_id = uuid.UUID(claims["organization_id"])
    workspace_id = uuid.UUID(claims["workspace_id"])
    user_id = uuid.UUID(claims["user_id"])
    platform = claims["platform"]
    adapter = get_platform_adapter(platform)
    service = PublishingService(session, platform_adapter=adapter, secrets=secrets, object_storage=object_storage)
    result = await service.connect_platform(
        organization_id=organization_id, workspace_id=workspace_id, user_id=user_id, platform=platform, code=code,
    )

    if isinstance(result, PendingAccountSelection):
        pending_token = create_pending_connection_token(
            organization_id=organization_id, workspace_id=workspace_id, user_id=user_id, platform=platform,
            user_token_secret_ref=result.user_token_secret_ref,
        )
        return PendingPageSelectionOut(
            pending_token=pending_token,
            accounts=[
                ConnectableAccountOut(external_account_id=a.external_account_id, external_account_name=a.external_account_name)
                for a in result.accounts
            ],
        )

    repo = PublishingRepository(session)
    return await _connection_detail(repo, result)


@router.post("/oauth/select-page", response_model=ConnectionDetailOut)
async def select_page(
    body: SelectPageRequest,
    session: AsyncSession = Depends(get_db_session),
    secrets: SecretsPort = Depends(get_secrets),
    object_storage: ObjectStoragePort = Depends(get_object_storage),
) -> ConnectionDetailOut:
    """Finalizes a connection deferred by /oauth/callback's multi-Page
    case. No Bearer auth — same reasoning as /oauth/callback, the caller
    is a page freshly loaded off a redirect, not an authenticated API
    client; pending_token (short-lived, signed) carries who's connecting
    what instead."""
    try:
        claims = decode_pending_connection_token(body.pending_token)
    except InvalidOAuthState as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc

    platform = claims["platform"]
    adapter = get_platform_adapter(platform)
    service = PublishingService(session, platform_adapter=adapter, secrets=secrets, object_storage=object_storage)
    connection = await service.select_account(
        organization_id=uuid.UUID(claims["organization_id"]),
        workspace_id=uuid.UUID(claims["workspace_id"]),
        user_id=uuid.UUID(claims["user_id"]),
        platform=platform,
        user_token_secret_ref=claims["user_token_secret_ref"],
        external_account_id=body.external_account_id,
    )

    repo = PublishingRepository(session)
    return await _connection_detail(repo, connection)


@router.get("/connections", response_model=list[ConnectionDetailOut])
async def list_connections(
    context: WorkspaceContext = Depends(get_workspace_context),
    session: AsyncSession = Depends(get_db_session),
) -> list[ConnectionDetailOut]:
    repo = PublishingRepository(session)
    connections = await repo.list_connections_for_workspace(context.workspace_id)
    return [await _connection_detail(repo, c) for c in connections]


@router.post("/plans", response_model=CreatePublicationPlanResponse, status_code=status.HTTP_201_CREATED)
async def create_publication_plan(
    body: CreatePublicationPlanRequest,
    current_user: User = Depends(get_current_user),
    context: WorkspaceContext = Depends(get_workspace_context),
    session: AsyncSession = Depends(get_db_session),
    temporal: Client = Depends(get_temporal_client_dep),
) -> CreatePublicationPlanResponse:
    repo = PublishingRepository(session)
    connection = await repo.get_connection_by_id(body.platform_connection_id)
    if connection is None or connection.workspace_id != context.workspace_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Platform connection not found")

    plan = await repo.create_publication_plan(
        organization_id=context.organization_id,
        workspace_id=context.workspace_id,
        content_item_id=body.content_item_id,
        platform_connection_id=body.platform_connection_id,
        created_by_user_id=current_user.id,
        scheduled_for=body.scheduled_for,
        target_format=body.target_format,
    )
    await session.commit()

    settings = get_settings()
    workflow_id = f"publication-{plan.id}"
    workflow_input = PublicationWorkflowInput(plan_id=str(plan.id), correlation_id=get_correlation_id())
    await temporal.start_workflow(
        PublicationWorkflow.run,
        args=[workflow_input, body.scheduled_for.isoformat() if body.scheduled_for else None],
        id=workflow_id,
        task_queue=settings.temporal_task_queue,
    )
    await repo.set_plan_workflow_id(plan, workflow_id)
    await session.commit()

    return CreatePublicationPlanResponse(plan_id=plan.id)


@router.get("/plans", response_model=list[PublicationPlanOut])
async def list_publication_plans(
    context: WorkspaceContext = Depends(get_workspace_context),
    session: AsyncSession = Depends(get_db_session),
) -> list[PublicationPlanOut]:
    repo = PublishingRepository(session)
    plans = await repo.list_publication_plans_for_workspace(context.workspace_id)
    return [PublicationPlanOut.model_validate(p) for p in plans]


@router.get("/plans/{plan_id}", response_model=PublicationPlanOut)
async def get_publication_plan(
    plan_id: uuid.UUID,
    context: WorkspaceContext = Depends(get_workspace_context),
    session: AsyncSession = Depends(get_db_session),
) -> PublicationPlanOut:
    repo = PublishingRepository(session)
    plan = await repo.get_publication_plan_by_id(plan_id)
    if plan is None or plan.workspace_id != context.workspace_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Publication plan not found")
    return PublicationPlanOut.model_validate(plan)


@router.get("/plans/{plan_id}/attempts", response_model=list[PublicationAttemptDetailOut])
async def list_publication_attempts(
    plan_id: uuid.UUID,
    context: WorkspaceContext = Depends(get_workspace_context),
    session: AsyncSession = Depends(get_db_session),
) -> list[PublicationAttemptDetailOut]:
    repo = PublishingRepository(session)
    plan = await repo.get_publication_plan_by_id(plan_id)
    if plan is None or plan.workspace_id != context.workspace_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Publication plan not found")

    attempts = await repo.list_attempts_for_plan(plan_id)
    results = []
    for attempt in attempts:
        reconciliations = await repo.list_reconciliations_for_attempt(attempt.id)
        results.append(
            PublicationAttemptDetailOut(
                attempt=PublicationAttemptOut.model_validate(attempt),
                reconciliations=[ReconciliationOut.model_validate(r) for r in reconciliations],
            )
        )
    return results


@router.post("/plans/{plan_id}/review", status_code=status.HTTP_202_ACCEPTED)
async def review_publication_plan(
    plan_id: uuid.UUID,
    body: PublicationReviewRequest,
    current_user: User = Depends(get_current_user),
    context: WorkspaceContext = Depends(get_workspace_context),
    session: AsyncSession = Depends(get_db_session),
    temporal: Client = Depends(get_temporal_client_dep),
) -> dict[str, str]:
    repo = PublishingRepository(session)
    plan = await repo.get_publication_plan_by_id(plan_id)
    if plan is None or plan.workspace_id != context.workspace_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Publication plan not found")
    if plan.status != "pending_approval":
        raise HTTPException(status.HTTP_409_CONFLICT, f"Plan is not awaiting approval (status={plan.status})")
    if plan.temporal_workflow_id is None:
        raise HTTPException(status.HTTP_409_CONFLICT, "Plan has no workflow to signal")

    handle = temporal.get_workflow_handle(plan.temporal_workflow_id)
    await handle.signal(
        PublicationWorkflow.submit_review,
        args=[body.decision, str(current_user.id), body.comment],
    )
    return {"status": "signal_sent"}


@router.delete("/plans/{plan_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_publication_plan(
    plan_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    context: WorkspaceContext = Depends(get_workspace_context),
    session: AsyncSession = Depends(get_db_session),
    secrets: SecretsPort = Depends(get_secrets),
    object_storage: ObjectStoragePort = Depends(get_object_storage),
) -> None:
    """Deletes this app's record of the plan — and, if it already
    published for real, the live post on the platform too (see
    PublishingService.delete_publication_plan's docstring). Irreversible
    on the platform's side once it runs."""
    repo = PublishingRepository(session)
    plan = await repo.get_publication_plan_by_id(plan_id)
    if plan is None or plan.workspace_id != context.workspace_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Publication plan not found")
    connection = await repo.get_connection_by_id(plan.platform_connection_id)
    if connection is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Platform connection not found")

    adapter = get_platform_adapter(connection.platform)
    service = PublishingService(session, platform_adapter=adapter, secrets=secrets, object_storage=object_storage)
    try:
        await service.delete_publication_plan(plan_id, current_user.id)
    except PlatformDeleteRejected as exc:
        # Surface the platform's own rejection instead of a bare 500 — the
        # local record deliberately survives this (see
        # PublishingService.delete_publication_plan), so it's safe to
        # retry once the underlying cause (commonly: the connected account
        # is missing a permission scope — reconnecting picks up
        # newly-requested scopes) is fixed.
        raise HTTPException(
            status.HTTP_502_BAD_GATEWAY,
            f"{exc.platform.capitalize()} refused to delete the live post — try reconnecting your "
            f"{exc.platform} account, then delete again. ({exc.detail})",
        ) from exc
