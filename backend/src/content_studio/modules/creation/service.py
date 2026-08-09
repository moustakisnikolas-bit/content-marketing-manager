import uuid
from decimal import Decimal

from sqlalchemy.ext.asyncio import AsyncSession

from content_studio.modules.billing.service import LedgerService
from content_studio.modules.creation.exceptions import AssetTooLarge
from content_studio.modules.creation.models import Asset
from content_studio.modules.creation.repository import CreationRepository
from content_studio.modules.governance.service import AuditService
from content_studio.ports.object_storage import ObjectStoragePort

# Phase 1 demonstrates the reserve -> settle ledger pattern with a flat,
# deterministic upload cost. Real per-operation pricing (driven by
# ModelPriceSnapshot / ContentRecipe) arrives with AI generation in Phase 2.
FLAT_UPLOAD_COST = Decimal("0.10")
MAX_UPLOAD_BYTES = 50 * 1024 * 1024


class AssetService:
    def __init__(
        self, session: AsyncSession, object_storage: ObjectStoragePort, ledger: LedgerService
    ) -> None:
        self._session = session
        self._repo = CreationRepository(session)
        self._object_storage = object_storage
        self._ledger = ledger
        self._audit = AuditService(session)

    async def upload_asset(
        self,
        *,
        organization_id: uuid.UUID,
        workspace_id: uuid.UUID,
        uploaded_by_user_id: uuid.UUID,
        subscription_id: uuid.UUID,
        filename: str,
        content_type: str,
        data: bytes,
    ) -> Asset:
        if len(data) > MAX_UPLOAD_BYTES:
            raise AssetTooLarge(f"{len(data)} bytes exceeds {MAX_UPLOAD_BYTES}")

        idempotency_key = f"asset_upload:{uuid.uuid4()}"
        reservation = await self._ledger.reserve(
            organization_id=organization_id,
            subscription_id=subscription_id,
            amount=FLAT_UPLOAD_COST,
            reference=f"asset_upload:{filename}",
            idempotency_key=idempotency_key,
        )

        storage_key = f"assets/{organization_id}/{uuid.uuid4()}/{filename}"
        await self._object_storage.put_object(key=storage_key, data=data, content_type=content_type)

        asset = await self._repo.create_asset(
            organization_id=organization_id,
            workspace_id=workspace_id,
            uploaded_by_user_id=uploaded_by_user_id,
            storage_key=storage_key,
            original_filename=filename,
            content_type=content_type,
            byte_size=len(data),
        )

        await self._ledger.settle(reservation_id=reservation.id, actual_amount=FLAT_UPLOAD_COST)
        await self._audit.record(
            event_type="asset.uploaded",
            actor_type="user",
            actor_id=str(uploaded_by_user_id),
            organization_id=organization_id,
            summary=f"Uploaded '{filename}' ({len(data)} bytes)",
            payload={"asset_id": str(asset.id), "storage_key": storage_key, "cost": str(FLAT_UPLOAD_COST)},
        )
        await self._session.commit()
        return asset

    async def get_download_url(self, asset: Asset) -> str:
        return await self._object_storage.get_presigned_url(key=asset.storage_key)
