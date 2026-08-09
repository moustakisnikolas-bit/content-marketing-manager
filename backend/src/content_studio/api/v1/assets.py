import uuid

from fastapi import APIRouter, Depends, HTTPException, UploadFile, status
from sqlalchemy.ext.asyncio import AsyncSession

from content_studio.api.deps import (
    WorkspaceContext,
    get_current_user,
    get_db_session,
    get_object_storage,
    get_workspace_context,
)
from content_studio.modules.billing.exceptions import InsufficientCredits
from content_studio.modules.billing.service import LedgerService
from content_studio.modules.creation.exceptions import AssetTooLarge
from content_studio.modules.creation.repository import CreationRepository
from content_studio.modules.creation.schemas import AssetDownloadUrlOut, AssetOut
from content_studio.modules.creation.service import AssetService
from content_studio.modules.identity.models import User
from content_studio.ports.object_storage import ObjectStoragePort

router = APIRouter(prefix="/assets", tags=["assets"])


@router.post("/upload", response_model=AssetOut, status_code=status.HTTP_201_CREATED)
async def upload_asset(
    file: UploadFile,
    current_user: User = Depends(get_current_user),
    context: WorkspaceContext = Depends(get_workspace_context),
    session: AsyncSession = Depends(get_db_session),
    object_storage: ObjectStoragePort = Depends(get_object_storage),
) -> AssetOut:
    data = await file.read()
    service = AssetService(session, object_storage, LedgerService(session))
    try:
        asset = await service.upload_asset(
            organization_id=context.organization_id,
            workspace_id=context.workspace_id,
            uploaded_by_user_id=current_user.id,
            subscription_id=context.subscription_id,
            filename=file.filename or "upload",
            content_type=file.content_type or "application/octet-stream",
            data=data,
        )
    except AssetTooLarge as exc:
        raise HTTPException(status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, str(exc)) from exc
    except InsufficientCredits as exc:
        raise HTTPException(status.HTTP_402_PAYMENT_REQUIRED, str(exc)) from exc

    return AssetOut.model_validate(asset)


@router.get("", response_model=list[AssetOut])
async def list_assets(
    context: WorkspaceContext = Depends(get_workspace_context),
    session: AsyncSession = Depends(get_db_session),
) -> list[AssetOut]:
    repo = CreationRepository(session)
    assets = await repo.list_assets_for_workspace(context.workspace_id)
    return [AssetOut.model_validate(a) for a in assets]


@router.get("/{asset_id}/download-url", response_model=AssetDownloadUrlOut)
async def get_asset_download_url(
    asset_id: uuid.UUID,
    context: WorkspaceContext = Depends(get_workspace_context),
    session: AsyncSession = Depends(get_db_session),
    object_storage: ObjectStoragePort = Depends(get_object_storage),
) -> AssetDownloadUrlOut:
    repo = CreationRepository(session)
    asset = await repo.get_asset_by_id(asset_id)
    if asset is None or asset.workspace_id != context.workspace_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Asset not found")

    service = AssetService(session, object_storage, LedgerService(session))
    url = await service.get_download_url(asset)
    return AssetDownloadUrlOut(url=url)
