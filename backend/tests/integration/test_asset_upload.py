import uuid
from decimal import Decimal

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from content_studio.modules.billing.exceptions import InsufficientCredits
from content_studio.modules.billing.repository import BillingRepository
from content_studio.modules.billing.service import LedgerService
from content_studio.modules.creation.exceptions import AssetTooLarge
from content_studio.modules.creation.service import FLAT_UPLOAD_COST, MAX_UPLOAD_BYTES, AssetService
from content_studio.modules.identity.service import IdentityService
from tests.fakes.object_storage import FakeObjectStorage

pytestmark = pytest.mark.asyncio


async def _seed_workspace_with_subscription(
    session: AsyncSession, *, allowance: Decimal = Decimal(100)
) -> tuple[uuid.UUID, uuid.UUID, uuid.UUID, uuid.UUID]:
    """Returns (organization_id, workspace_id, user_id, subscription_id)."""
    identity = IdentityService(session)
    email = f"asset-{uuid.uuid4().hex[:12]}@example.com"
    signup = await identity.signup(
        email=email, password="correct-horse-battery", display_name="Asset Test", organization_name="Asset Org"
    )

    billing_repo = BillingRepository(session)
    plan_slug = f"plan-{uuid.uuid4().hex[:8]}"
    plan = await billing_repo.create_plan(
        name=plan_slug, slug=plan_slug, monthly_price=Decimal("39.00"), monthly_credit_allowance=allowance
    )
    await session.commit()

    ledger = LedgerService(session)
    subscription_id = await ledger.open_subscription(
        organization_id=signup.organization.id, plan_slug=plan.slug
    )
    return signup.organization.id, signup.workspace.id, signup.user.id, subscription_id


async def test_upload_asset_stores_bytes_and_settles_flat_cost(db_session: AsyncSession) -> None:
    org_id, workspace_id, user_id, subscription_id = await _seed_workspace_with_subscription(db_session)
    storage = FakeObjectStorage()
    ledger = LedgerService(db_session)
    service = AssetService(db_session, storage, ledger)

    asset = await service.upload_asset(
        organization_id=org_id,
        workspace_id=workspace_id,
        uploaded_by_user_id=user_id,
        subscription_id=subscription_id,
        filename="brand-logo.png",
        content_type="image/png",
        data=b"fake-png-bytes",
    )

    assert asset.original_filename == "brand-logo.png"
    assert asset.byte_size == len(b"fake-png-bytes")
    stored_bytes, stored_content_type = storage.objects[asset.storage_key]
    assert stored_bytes == b"fake-png-bytes"
    assert stored_content_type == "image/png"

    balance = await ledger.get_balance(subscription_id)
    assert balance == Decimal(100) - FLAT_UPLOAD_COST


async def test_upload_asset_rejects_oversized_file(db_session: AsyncSession) -> None:
    org_id, workspace_id, user_id, subscription_id = await _seed_workspace_with_subscription(db_session)
    storage = FakeObjectStorage()
    service = AssetService(db_session, storage, LedgerService(db_session))

    with pytest.raises(AssetTooLarge):
        await service.upload_asset(
            organization_id=org_id,
            workspace_id=workspace_id,
            uploaded_by_user_id=user_id,
            subscription_id=subscription_id,
            filename="huge.bin",
            content_type="application/octet-stream",
            data=b"0" * (MAX_UPLOAD_BYTES + 1),
        )
    assert storage.objects == {}


async def test_upload_asset_raises_when_insufficient_credits(db_session: AsyncSession) -> None:
    org_id, workspace_id, user_id, subscription_id = await _seed_workspace_with_subscription(
        db_session, allowance=Decimal("0.05")
    )
    storage = FakeObjectStorage()
    service = AssetService(db_session, storage, LedgerService(db_session))

    with pytest.raises(InsufficientCredits):
        await service.upload_asset(
            organization_id=org_id,
            workspace_id=workspace_id,
            uploaded_by_user_id=user_id,
            subscription_id=subscription_id,
            filename="too-expensive.png",
            content_type="image/png",
            data=b"bytes",
        )
    # No orphaned object left behind since the reservation happens before
    # the storage write.
    assert storage.objects == {}


async def test_get_download_url_returns_presigned_style_url(db_session: AsyncSession) -> None:
    org_id, workspace_id, user_id, subscription_id = await _seed_workspace_with_subscription(db_session)
    storage = FakeObjectStorage()
    service = AssetService(db_session, storage, LedgerService(db_session))

    asset = await service.upload_asset(
        organization_id=org_id,
        workspace_id=workspace_id,
        uploaded_by_user_id=user_id,
        subscription_id=subscription_id,
        filename="track.mp3",
        content_type="audio/mpeg",
        data=b"fake-audio-bytes",
    )

    url = await service.get_download_url(asset)
    assert url.startswith("fake://")
    assert asset.storage_key in url
