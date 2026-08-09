import uuid
from decimal import Decimal

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from content_studio.modules.billing.repository import BillingRepository
from content_studio.modules.billing.service import LedgerService
from content_studio.modules.creation.generation_service import GenerationService
from content_studio.modules.creation.repository import CreationRepository
from content_studio.modules.identity.service import IdentityService
from tests.fakes.ai_audio import FakeAIAudio
from tests.fakes.ai_image import FakeAIImage
from tests.fakes.ai_text import FakeAIText
from tests.fakes.object_storage import FakeObjectStorage

pytestmark = pytest.mark.asyncio


async def _seed_audio_job(session: AsyncSession, *, allowance: Decimal = Decimal(100)) -> dict:
    identity = IdentityService(session)
    email = f"audio-{uuid.uuid4().hex[:12]}@example.com"
    signup = await identity.signup(
        email=email, password="correct-horse-battery", display_name="Audio Test", organization_name="Audio Org"
    )

    billing_repo = BillingRepository(session)
    plan_slug = f"plan-{uuid.uuid4().hex[:8]}"
    plan = await billing_repo.create_plan(
        name=plan_slug, slug=plan_slug, monthly_price=Decimal("39.00"), monthly_credit_allowance=allowance
    )
    await session.commit()

    ledger = LedgerService(session)
    subscription_id = await ledger.open_subscription(organization_id=signup.organization.id, plan_slug=plan.slug)

    repo = CreationRepository(session)
    recipe = await repo.create_recipe(
        name=f"audio-recipe-{uuid.uuid4().hex[:8]}", content_type="audio", provider="replicate",
        model="test-audio-model", estimated_cost=Decimal("1.5"),
    )
    item = await repo.create_content_item(
        organization_id=signup.organization.id, workspace_id=signup.workspace.id,
        created_by_user_id=signup.user.id, content_type="audio", title="Summer sale voiceover",
    )
    job = await repo.create_generation_job(
        organization_id=signup.organization.id, workspace_id=signup.workspace.id, content_item_id=item.id,
        recipe_id=recipe.id, requested_by_user_id=signup.user.id, subscription_id=subscription_id,
        brief_text="An upbeat 15-second voiceover announcing our summer sale",
    )
    await session.commit()

    return {
        "organization_id": signup.organization.id, "workspace_id": signup.workspace.id, "user_id": signup.user.id,
        "subscription_id": subscription_id, "recipe": recipe, "item": item, "job": job,
    }


def _service(session: AsyncSession, *, ai_audio=None) -> GenerationService:
    return GenerationService(
        session, ai_text=FakeAIText(), ai_image=FakeAIImage(), ai_audio=ai_audio or FakeAIAudio(),
        object_storage=FakeObjectStorage(),
    )


async def test_full_audio_generation_lifecycle_produces_an_asset(db_session: AsyncSession) -> None:
    ctx = await _seed_audio_job(db_session)
    fake_audio = FakeAIAudio()
    service = _service(db_session, ai_audio=fake_audio)

    reserve_result = await service.reserve_cost(ctx["job"].id)
    assert reserve_result.ok

    dispatch_result = await service.dispatch(ctx["job"].id)
    assert dispatch_result.ok
    assert len(fake_audio.calls) == 1
    assert fake_audio.calls[0]["prompt"] == ctx["job"].brief_text

    repo = CreationRepository(db_session)
    revision = await repo.get_revision_by_id(uuid.UUID(dispatch_result.revision_id))
    assert revision.asset_id is not None
    assert revision.text_body is None

    asset = await repo.get_asset_by_id(revision.asset_id)
    assert asset.content_type == "audio/wav"
    assert asset.byte_size > 0

    # No brand profile attached — quality gate is a pass-through for audio,
    # same as image (media quality gates are a later extension).
    gate_result = await service.run_quality_gate(ctx["job"].id, revision.id)
    assert gate_result.passed is True

    package_id = await service.finalize_approved(ctx["job"].id, revision.id, ctx["user_id"], "sounds great")
    assert package_id is not None

    ledger = LedgerService(db_session)
    balance = await ledger.get_balance(ctx["subscription_id"])
    assert balance == Decimal("98.5000")


async def test_audio_dispatch_without_ai_audio_adapter_fails_cleanly(db_session: AsyncSession) -> None:
    """GenerationService's ai_audio port is optional (Auto-Pilot's
    text-only campaigns don't need it) — but a caller that omits it must
    get a clear failure for an audio job, not a silent no-op or an
    unrelated AttributeError."""
    ctx = await _seed_audio_job(db_session)
    service = GenerationService(
        db_session, ai_text=FakeAIText(), ai_image=FakeAIImage(), object_storage=FakeObjectStorage(),
    )

    await service.reserve_cost(ctx["job"].id)
    dispatch_result = await service.dispatch(ctx["job"].id)

    assert not dispatch_result.ok
    assert "AIAudioPort" in dispatch_result.error


async def test_audio_generation_failure_releases_reservation(db_session: AsyncSession) -> None:
    ctx = await _seed_audio_job(db_session)
    service = _service(db_session, ai_audio=FakeAIAudio(should_fail=True))

    await service.reserve_cost(ctx["job"].id)
    dispatch_result = await service.dispatch(ctx["job"].id)
    assert not dispatch_result.ok

    ledger = LedgerService(db_session)
    balance = await ledger.get_balance(ctx["subscription_id"])
    assert balance == Decimal("100.0000")

    repo = CreationRepository(db_session)
    job = await repo.get_generation_job_by_id(ctx["job"].id)
    assert job.status == "failed"
