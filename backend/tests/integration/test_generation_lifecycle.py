import uuid
from decimal import Decimal

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from content_studio.modules.billing.repository import BillingRepository
from content_studio.modules.billing.service import LedgerService
from content_studio.modules.creation.generation_service import GenerationService
from content_studio.modules.creation.repository import CreationRepository
from content_studio.modules.identity.service import IdentityService
from tests.fakes.ai_image import FakeAIImage
from tests.fakes.ai_text import FakeAIText
from tests.fakes.object_storage import FakeObjectStorage

pytestmark = pytest.mark.asyncio


async def _seed_workspace(session: AsyncSession, *, allowance: Decimal = Decimal(100)) -> dict:
    identity = IdentityService(session)
    email = f"gen-{uuid.uuid4().hex[:12]}@example.com"
    signup = await identity.signup(
        email=email, password="correct-horse-battery", display_name="Gen Test", organization_name="Gen Org"
    )

    billing_repo = BillingRepository(session)
    plan_slug = f"plan-{uuid.uuid4().hex[:8]}"
    plan = await billing_repo.create_plan(
        name=plan_slug, slug=plan_slug, monthly_price=Decimal("39.00"), monthly_credit_allowance=allowance
    )
    await session.commit()

    ledger = LedgerService(session)
    subscription_id = await ledger.open_subscription(organization_id=signup.organization.id, plan_slug=plan.slug)

    return {
        "organization_id": signup.organization.id,
        "workspace_id": signup.workspace.id,
        "user_id": signup.user.id,
        "subscription_id": subscription_id,
    }


async def _seed_text_job(session: AsyncSession, *, allowance: Decimal = Decimal(100), estimated_cost: Decimal = Decimal("0.5")) -> dict:
    ctx = await _seed_workspace(session, allowance=allowance)
    repo = CreationRepository(session)

    recipe = await repo.create_recipe(
        name=f"recipe-{uuid.uuid4().hex[:8]}",
        content_type="text",
        provider="openrouter",
        model="test-model",
        estimated_cost=estimated_cost,
    )
    item = await repo.create_content_item(
        organization_id=ctx["organization_id"],
        workspace_id=ctx["workspace_id"],
        created_by_user_id=ctx["user_id"],
        content_type="text",
        title="Test caption",
    )
    job = await repo.create_generation_job(
        organization_id=ctx["organization_id"],
        workspace_id=ctx["workspace_id"],
        content_item_id=item.id,
        recipe_id=recipe.id,
        requested_by_user_id=ctx["user_id"],
        subscription_id=ctx["subscription_id"],
        brief_text="Write a caption for our summer sale",
    )
    await session.commit()
    ctx.update({"recipe": recipe, "item": item, "job": job})
    return ctx


def _service(session: AsyncSession, *, ai_text=None, ai_image=None, object_storage=None) -> GenerationService:
    return GenerationService(
        session,
        ai_text=ai_text or FakeAIText(),
        ai_image=ai_image or FakeAIImage(),
        object_storage=object_storage or FakeObjectStorage(),
    )


async def test_reserve_cost_deducts_balance_and_marks_job_generating(db_session: AsyncSession) -> None:
    ctx = await _seed_text_job(db_session, allowance=Decimal(100), estimated_cost=Decimal("0.5"))
    service = _service(db_session)

    result = await service.reserve_cost(ctx["job"].id)
    assert result.ok

    ledger = LedgerService(db_session)
    balance = await ledger.get_balance(ctx["subscription_id"])
    assert balance == Decimal("99.5000")

    repo = CreationRepository(db_session)
    job = await repo.get_generation_job_by_id(ctx["job"].id)
    assert job.status == "generating"
    assert job.cost_reservation_id is not None


async def test_reserve_cost_fails_job_when_insufficient_credits(db_session: AsyncSession) -> None:
    ctx = await _seed_text_job(db_session, allowance=Decimal("0.1"), estimated_cost=Decimal(5))
    service = _service(db_session)

    result = await service.reserve_cost(ctx["job"].id)
    assert not result.ok

    repo = CreationRepository(db_session)
    job = await repo.get_generation_job_by_id(ctx["job"].id)
    assert job.status == "failed"


async def test_dispatch_text_creates_revision_and_settles_cost(db_session: AsyncSession) -> None:
    ctx = await _seed_text_job(db_session, allowance=Decimal(100), estimated_cost=Decimal("0.5"))
    fake_text = FakeAIText(fixed_response="Sunny days call for sweet deals.")
    service = _service(db_session, ai_text=fake_text)

    reserve_result = await service.reserve_cost(ctx["job"].id)
    assert reserve_result.ok

    dispatch_result = await service.dispatch(ctx["job"].id)
    assert dispatch_result.ok
    assert dispatch_result.revision_id is not None
    assert len(fake_text.calls) == 1
    assert fake_text.calls[0]["prompt"] == "Write a caption for our summer sale"

    repo = CreationRepository(db_session)
    revision = await repo.get_revision_by_id(uuid.UUID(dispatch_result.revision_id))
    assert revision.text_body == "Sunny days call for sweet deals."
    assert revision.kind == "draft_preview"

    ledger = LedgerService(db_session)
    balance = await ledger.get_balance(ctx["subscription_id"])
    assert balance == Decimal("99.5000")  # settled at the estimated cost, no variance


async def test_dispatch_image_stores_asset_via_object_storage(db_session: AsyncSession) -> None:
    ctx = await _seed_workspace(db_session)
    repo = CreationRepository(db_session)
    recipe = await repo.create_recipe(
        name=f"recipe-{uuid.uuid4().hex[:8]}", content_type="image", provider="replicate", model="test-model",
        estimated_cost=Decimal(2),
    )
    item = await repo.create_content_item(
        organization_id=ctx["organization_id"], workspace_id=ctx["workspace_id"],
        created_by_user_id=ctx["user_id"], content_type="image", title="Product shot",
    )
    job = await repo.create_generation_job(
        organization_id=ctx["organization_id"], workspace_id=ctx["workspace_id"], content_item_id=item.id,
        recipe_id=recipe.id, requested_by_user_id=ctx["user_id"], subscription_id=ctx["subscription_id"],
        brief_text="A product photo on a white background",
    )
    await db_session.commit()

    storage = FakeObjectStorage()
    fake_image = FakeAIImage()
    service = _service(db_session, ai_image=fake_image, object_storage=storage)

    assert (await service.reserve_cost(job.id)).ok
    dispatch_result = await service.dispatch(job.id)
    assert dispatch_result.ok
    assert len(fake_image.calls) == 1
    assert len(storage.objects) == 1

    revision = await repo.get_revision_by_id(uuid.UUID(dispatch_result.revision_id))
    assert revision.asset_id is not None


async def test_dispatch_failure_releases_reservation_and_fails_job(db_session: AsyncSession) -> None:
    ctx = await _seed_text_job(db_session, allowance=Decimal(100), estimated_cost=Decimal("0.5"))
    service = _service(db_session, ai_text=FakeAIText(should_fail=True))

    assert (await service.reserve_cost(ctx["job"].id)).ok
    dispatch_result = await service.dispatch(ctx["job"].id)
    assert not dispatch_result.ok

    ledger = LedgerService(db_session)
    balance = await ledger.get_balance(ctx["subscription_id"])
    assert balance == Decimal("100.0000")  # fully refunded, nothing was produced

    repo = CreationRepository(db_session)
    job = await repo.get_generation_job_by_id(ctx["job"].id)
    assert job.status == "failed"


async def test_quality_gate_passes_with_no_brand_profile(db_session: AsyncSession) -> None:
    ctx = await _seed_text_job(db_session)
    service = _service(db_session, ai_text=FakeAIText(fixed_response="Totally fine copy"))
    await service.reserve_cost(ctx["job"].id)
    dispatch_result = await service.dispatch(ctx["job"].id)

    gate_result = await service.run_quality_gate(ctx["job"].id, uuid.UUID(dispatch_result.revision_id))
    assert gate_result.passed

    repo = CreationRepository(db_session)
    job = await repo.get_generation_job_by_id(ctx["job"].id)
    assert job.status == "awaiting_review"


async def test_quality_gate_blocks_forbidden_claim(db_session: AsyncSession) -> None:
    from content_studio.modules.identity.models import BrandProfile, BrandRule

    ctx = await _seed_text_job(db_session)
    brand_profile = BrandProfile(workspace_id=ctx["workspace_id"], name="Test Brand")
    db_session.add(brand_profile)
    await db_session.flush()
    db_session.add(
        BrandRule(
            brand_profile_id=brand_profile.id,
            rule_type="forbidden_claim",
            description="guaranteed results",
            is_blocking=True,
        )
    )
    await db_session.commit()

    repo = CreationRepository(db_session)
    item = await repo.get_content_item_by_id(ctx["item"].id)
    item.brand_profile_id = brand_profile.id
    await db_session.commit()

    service = _service(db_session, ai_text=FakeAIText(fixed_response="We offer guaranteed results for everyone!"))
    await service.reserve_cost(ctx["job"].id)
    dispatch_result = await service.dispatch(ctx["job"].id)

    gate_result = await service.run_quality_gate(ctx["job"].id, uuid.UUID(dispatch_result.revision_id))
    assert not gate_result.passed
    assert "guaranteed results" in gate_result.violations[0]

    job = await repo.get_generation_job_by_id(ctx["job"].id)
    assert job.status == "quality_gate_failed"


async def test_finalize_approved_creates_package_and_promotes_revision(db_session: AsyncSession) -> None:
    ctx = await _seed_text_job(db_session)
    service = _service(db_session, ai_text=FakeAIText(fixed_response="Approved-ready copy"))
    await service.reserve_cost(ctx["job"].id)
    dispatch_result = await service.dispatch(ctx["job"].id)
    await service.run_quality_gate(ctx["job"].id, uuid.UUID(dispatch_result.revision_id))

    package_id = await service.finalize_approved(
        ctx["job"].id, uuid.UUID(dispatch_result.revision_id), ctx["user_id"], "looks great"
    )
    assert package_id is not None

    repo = CreationRepository(db_session)
    revision = await repo.get_revision_by_id(uuid.UUID(dispatch_result.revision_id))
    assert revision.kind == "final_render"

    job = await repo.get_generation_job_by_id(ctx["job"].id)
    assert job.status == "approved"

    item = await repo.get_content_item_by_id(ctx["item"].id)
    assert item.status == "approved"

    package = await repo.get_package_for_item(ctx["item"].id)
    assert str(package.id) == package_id
    assert package.selected_revision_id == revision.id


async def test_finalize_rejected_does_not_create_package(db_session: AsyncSession) -> None:
    ctx = await _seed_text_job(db_session)
    service = _service(db_session, ai_text=FakeAIText(fixed_response="Needs work"))
    await service.reserve_cost(ctx["job"].id)
    dispatch_result = await service.dispatch(ctx["job"].id)
    await service.run_quality_gate(ctx["job"].id, uuid.UUID(dispatch_result.revision_id))

    await service.finalize_rejected(
        ctx["job"].id, uuid.UUID(dispatch_result.revision_id), ctx["user_id"], "not on brand"
    )

    repo = CreationRepository(db_session)
    job = await repo.get_generation_job_by_id(ctx["job"].id)
    assert job.status == "rejected"
    assert job.failure_reason == "not on brand"

    item = await repo.get_content_item_by_id(ctx["item"].id)
    assert item.status == "rejected"

    package = await repo.get_package_for_item(ctx["item"].id)
    assert package is None
