import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from content_studio.api.deps import (
    WorkspaceContext,
    get_current_user,
    get_db_session,
    require_permission,
)
from content_studio.modules.identity.api_key_service import ApiKeyService
from content_studio.modules.identity.exceptions import ApiKeyNotFound
from content_studio.modules.identity.models import User
from content_studio.modules.identity.repository import IdentityRepository
from content_studio.modules.identity.schemas import (
    ApiKeyOut,
    CreateApiKeyRequest,
    CreateApiKeyResponse,
)

router = APIRouter(prefix="/api-keys", tags=["api-keys"])


@router.post("", response_model=CreateApiKeyResponse, status_code=status.HTTP_201_CREATED)
async def create_api_key(
    body: CreateApiKeyRequest,
    current_user: User = Depends(get_current_user),
    context: WorkspaceContext = Depends(require_permission("workspace:manage")),
    session: AsyncSession = Depends(get_db_session),
) -> CreateApiKeyResponse:
    service = ApiKeyService(session)
    api_key, raw_key = await service.create_api_key(
        organization_id=context.organization_id, workspace_id=context.workspace_id,
        created_by_user_id=current_user.id, name=body.name, scopes=body.scopes,
    )
    return CreateApiKeyResponse(api_key=ApiKeyOut.model_validate(api_key), raw_key=raw_key)


@router.get("", response_model=list[ApiKeyOut])
async def list_api_keys(
    context: WorkspaceContext = Depends(require_permission("workspace:manage")),
    session: AsyncSession = Depends(get_db_session),
) -> list[ApiKeyOut]:
    repo = IdentityRepository(session)
    keys = await repo.list_api_keys_for_workspace(context.workspace_id)
    return [ApiKeyOut.model_validate(k) for k in keys]


@router.post("/{api_key_id}/revoke", response_model=ApiKeyOut)
async def revoke_api_key(
    api_key_id: uuid.UUID,
    context: WorkspaceContext = Depends(require_permission("workspace:manage")),
    session: AsyncSession = Depends(get_db_session),
) -> ApiKeyOut:
    service = ApiKeyService(session)
    try:
        api_key = await service.revoke_api_key(api_key_id, workspace_id=context.workspace_id)
    except ApiKeyNotFound as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "API key not found") from exc
    return ApiKeyOut.model_validate(api_key)
