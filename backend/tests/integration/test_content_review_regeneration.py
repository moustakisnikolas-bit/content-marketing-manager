import uuid
from decimal import Decimal

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from content_studio.api.deps import WorkspaceContext
from content_studio.api.v1.content import regenerate_generation_job, review_generation_job
from content_studio.modules.billing.repository import BillingRepository
from content_studio.modules.billing.service import LedgerService
from content_studio.modules.creation.repository import CreationRepository
from content_studio.modules.creation.schemas import RegenerateJobRequest, ReviewRequest
from content_studio.modules.identity.service import IdentityService
from content_studio.modules.marketing.repository import MarketingRepository
from content_studio.modules.marketing.service import MarketingService

pytestmark = pytest.mark.asyncio


class _FakeWorkflowHandle:
    def __init__(self, signals: list) -> None:
        self._signals = signals

    async def signal(self, method, args) -> None:
        self._signals.append((method, args))


class _FakeTemporalClient:
    def __init__(self) -> None:
        self.signals: list = []
        self.started: list = []

    def get_workflow_handle(self, workflow_id: str) -> _FakeWorkflowHandle:
        return _FakeWorkflowHandle(self.signals)

    async def start_workflow(self, run_fn, input_arg, *, id: str, task_queue: str) -> None:
        self.started.append({"id": id, "input": input_arg})


async def _seed_workspace(session: AsyncSession, *, allowance: Decimal = Decimal(100)) -> dict:
    identity = IdentityService(session)
    email = f"revw-{uuid.uuid4().hex[:12]}@example.com"
    signup = await identity.signup(
        email=email, password="correct-horse-battery", display_name="Review Test", organization_name="Review Org"
    )

    billing_repo = BillingRepository(session)
    plan_slug = f"plan-{uuid.uuid4().hex[:8]}"
    plan = await billing_repo.create_plan(
        name=plan_slug, slug=plan_slug, monthly_price=Decimal("39.00"), monthly_credit_allowance=allowance
    )
    await session.commit()

    ledger = LedgerService(session)
    subscription_id = await ledger.open_subscription(organization_id=signup.organization.id, plan_slug=plan.slug)

    creation_repo = CreationRepository(session)
    recipe = await creation_repo.create_recipe(
        name=f"text-recipe-{uuid.uuid4().hex[:8]}", content_type="text", provider="openrouter", model="test-model",
        estimated_cost=Decimal("0.5"),
    )

    marketing_repo = MarketingRepository(session)
    goal = await marketing_repo.get_goal_by_slug("brand_awareness")
    if goal is None:
        goal = await marketing_repo.create_goal(
            slug="brand_awareness", label="Brand awareness", description="Get more people to know you"
        )
    await session.commit()

    return {
        "user": signup.user,
        "organization_id": signup.organization.id,
        "workspace_id": signup.workspace.id,
        "subscription_id": subscription_id,
        "recipe": recipe,
        "goal_slug": goal.slug,
    }


async def _seed_awaiting_review_job(session: AsyncSession, ctx: dict, *, reference_image_url: str | None = None) -> dict:
    repo = CreationRepository(session)
    item = await repo.create_content_item(
        organization_id=ctx["organization_id"], workspace_id=ctx["workspace_id"],
        created_by_user_id=ctx["user"].id, content_type="text", title="Original item",
    )
    job = await repo.create_generation_job(
        organization_id=ctx["organization_id"], workspace_id=ctx["workspace_id"], content_item_id=item.id,
        recipe_id=ctx["recipe"].id, requested_by_user_id=ctx["user"].id, subscription_id=ctx["subscription_id"],
        brief_text="Write a caption for our summer sale", reference_image_url=reference_image_url,
    )
    await repo.update_job_status(job, "awaiting_review")
    await repo.set_job_workflow_id(job, f"generation-{job.id}")
    await session.commit()
    return {"item": item, "job": job}


def _context(ctx: dict) -> WorkspaceContext:
    return WorkspaceContext(
        organization_id=ctx["organization_id"], workspace_id=ctx["workspace_id"],
        subscription_id=ctx["subscription_id"], role_permissions=[],
    )


async def test_reject_with_comment_creates_new_job_with_augmented_brief(db_session: AsyncSession) -> None:
    ctx = await _seed_workspace(db_session)
    seeded = await _seed_awaiting_review_job(db_session, ctx, reference_image_url="https://example.com/ref.jpg")
    temporal = _FakeTemporalClient()

    result = await review_generation_job(
        job_id=seeded["job"].id,
        body=ReviewRequest(decision="rejected", revision_id=uuid.uuid4(), comment="Make it punchier"),
        current_user=ctx["user"],
        context=_context(ctx),
        session=db_session,
        temporal=temporal,
    )

    assert result["status"] == "signal_sent"
    assert result["new_job_id"] is not None
    assert len(temporal.signals) == 1
    assert len(temporal.started) == 1

    repo = CreationRepository(db_session)
    new_job = await repo.get_generation_job_by_id(uuid.UUID(result["new_job_id"]))
    assert new_job is not None
    assert new_job.brief_text == "Write a caption for our summer sale\n\nRevision requested: Make it punchier"
    assert new_job.recipe_id == seeded["job"].recipe_id
    assert new_job.content_item_id == seeded["job"].content_item_id
    assert new_job.reference_image_url == "https://example.com/ref.jpg"
    assert new_job.temporal_workflow_id == f"generation-{new_job.id}"


async def test_reject_without_comment_reuses_original_brief(db_session: AsyncSession) -> None:
    ctx = await _seed_workspace(db_session)
    seeded = await _seed_awaiting_review_job(db_session, ctx)
    temporal = _FakeTemporalClient()

    result = await review_generation_job(
        job_id=seeded["job"].id,
        body=ReviewRequest(decision="rejected", revision_id=uuid.uuid4(), comment=None),
        current_user=ctx["user"],
        context=_context(ctx),
        session=db_session,
        temporal=temporal,
    )

    repo = CreationRepository(db_session)
    new_job = await repo.get_generation_job_by_id(uuid.UUID(result["new_job_id"]))
    assert new_job.brief_text == seeded["job"].brief_text


async def test_approve_does_not_create_new_job(db_session: AsyncSession) -> None:
    ctx = await _seed_workspace(db_session)
    seeded = await _seed_awaiting_review_job(db_session, ctx)
    temporal = _FakeTemporalClient()

    result = await review_generation_job(
        job_id=seeded["job"].id,
        body=ReviewRequest(decision="approved", revision_id=uuid.uuid4(), comment=None),
        current_user=ctx["user"],
        context=_context(ctx),
        session=db_session,
        temporal=temporal,
    )

    assert result["new_job_id"] is None
    assert len(temporal.started) == 0

    repo = CreationRepository(db_session)
    jobs = await repo.list_generation_jobs_for_workspace(ctx["workspace_id"])
    assert len(jobs) == 1


async def test_reject_repoints_linked_plan_item_to_new_job(db_session: AsyncSession) -> None:
    ctx = await _seed_workspace(db_session)
    marketing_service = MarketingService(db_session)
    brief = await marketing_service.create_brief(
        organization_id=ctx["organization_id"], workspace_id=ctx["workspace_id"], user_id=ctx["user"].id,
        goal_slug=ctx["goal_slug"], what_to_promote="our summer sale", mode="guided", target_platforms=["facebook"],
    )
    proposal = await marketing_service.generate_proposal(brief.id)
    campaign = await marketing_service.approve_proposal(
        proposal_id=proposal.id, user_id=ctx["user"].id, campaign_name="Summer Sale"
    )

    marketing_repo = MarketingRepository(db_session)
    plan_item = (await marketing_repo.list_plan_items_for_campaign(campaign.id))[0]

    seeded = await _seed_awaiting_review_job(db_session, ctx)
    await marketing_repo.link_plan_item_generation(
        plan_item, content_item_id=seeded["item"].id, generation_job_id=seeded["job"].id
    )

    found_before = await marketing_repo.list_plan_items_by_generation_job_id(seeded["job"].id)
    assert len(found_before) == 1
    assert found_before[0].id == plan_item.id

    temporal = _FakeTemporalClient()
    result = await review_generation_job(
        job_id=seeded["job"].id,
        body=ReviewRequest(decision="rejected", revision_id=uuid.uuid4(), comment="Different angle please"),
        current_user=ctx["user"],
        context=_context(ctx),
        session=db_session,
        temporal=temporal,
    )

    refreshed = await marketing_repo.get_plan_item_by_id(plan_item.id)
    assert str(refreshed.generation_job_id) == result["new_job_id"]
    assert refreshed.content_item_id == seeded["item"].id


async def test_regenerate_replaces_prompt_without_recording_a_decision(db_session: AsyncSession) -> None:
    """Distinct from Reject: replaces the prompt outright (no "Revision
    requested: ..." append), doesn't touch the old job's status, and
    doesn't signal its workflow — it's not a verdict, just superseded."""
    ctx = await _seed_workspace(db_session)
    marketing_service = MarketingService(db_session)
    brief = await marketing_service.create_brief(
        organization_id=ctx["organization_id"], workspace_id=ctx["workspace_id"], user_id=ctx["user"].id,
        goal_slug=ctx["goal_slug"], what_to_promote="our summer sale", mode="guided", target_platforms=["facebook"],
    )
    proposal = await marketing_service.generate_proposal(brief.id)
    campaign = await marketing_service.approve_proposal(
        proposal_id=proposal.id, user_id=ctx["user"].id, campaign_name="Summer Sale"
    )

    marketing_repo = MarketingRepository(db_session)
    plan_item = (await marketing_repo.list_plan_items_for_campaign(campaign.id))[0]

    seeded = await _seed_awaiting_review_job(db_session, ctx)
    await marketing_repo.link_plan_item_generation(
        plan_item, content_item_id=seeded["item"].id, generation_job_id=seeded["job"].id
    )
    await db_session.commit()

    temporal = _FakeTemporalClient()
    new_prompt = "A completely different scene: a rustic wooden table by a window, morning light."
    result = await regenerate_generation_job(
        job_id=seeded["job"].id,
        body=RegenerateJobRequest(brief_text=new_prompt),
        current_user=ctx["user"],
        context=_context(ctx),
        session=db_session,
        temporal=temporal,
    )

    assert len(temporal.signals) == 0  # not a reject — the old workflow is never signaled
    assert len(temporal.started) == 1  # only the new generation workflow starts

    creation_repo = CreationRepository(db_session)
    old_job = await creation_repo.get_generation_job_by_id(seeded["job"].id)
    assert old_job.status == "awaiting_review"  # untouched — no verdict recorded on it

    new_job = await creation_repo.get_generation_job_by_id(result.new_job_id)
    assert new_job.brief_text == new_prompt  # replaced outright, not appended
    assert new_job.content_item_id == seeded["item"].id

    refreshed = await marketing_repo.get_plan_item_by_id(plan_item.id)
    assert refreshed.generation_job_id == result.new_job_id
    assert refreshed.brief_text == new_prompt


async def test_regenerate_cascades_to_every_plan_item_sharing_the_job(db_session: AsyncSession) -> None:
    """A shared image (see build_bulk_plan_items' one-pair-per-platform
    design) referenced by two plan items must have both re-pointed to the
    freshly regenerated job, not just whichever one triggered the call."""
    ctx = await _seed_workspace(db_session)
    marketing_service = MarketingService(db_session)
    brief = await marketing_service.create_brief(
        organization_id=ctx["organization_id"], workspace_id=ctx["workspace_id"], user_id=ctx["user"].id,
        goal_slug=ctx["goal_slug"], what_to_promote="our summer sale", mode="guided", target_platforms=["facebook"],
    )
    proposal = await marketing_service.generate_proposal(brief.id)
    campaign = await marketing_service.approve_proposal(
        proposal_id=proposal.id, user_id=ctx["user"].id, campaign_name="Summer Sale"
    )

    marketing_repo = MarketingRepository(db_session)
    text_item = (await marketing_repo.list_plan_items_for_campaign(campaign.id))[0]
    image_item_a = await marketing_repo.create_plan_item(
        campaign_id=campaign.id, sequence_number=90, title="Product (facebook image)", brief_text="n/a",
        target_platform="facebook", content_type="image",
    )
    image_item_b = await marketing_repo.create_plan_item(
        campaign_id=campaign.id, sequence_number=91, title="Product (instagram image)", brief_text="n/a",
        target_platform="instagram", content_type="image",
    )

    seeded = await _seed_awaiting_review_job(db_session, ctx)
    await marketing_repo.link_plan_item_generation(
        image_item_a, content_item_id=seeded["item"].id, generation_job_id=seeded["job"].id
    )
    await marketing_repo.link_plan_item_generation(
        image_item_b, content_item_id=seeded["item"].id, generation_job_id=seeded["job"].id
    )
    await db_session.commit()

    result = await regenerate_generation_job(
        job_id=seeded["job"].id,
        body=RegenerateJobRequest(brief_text="A different background scene entirely."),
        current_user=ctx["user"],
        context=_context(ctx),
        session=db_session,
        temporal=_FakeTemporalClient(),
    )

    refreshed_a = await marketing_repo.get_plan_item_by_id(image_item_a.id)
    refreshed_b = await marketing_repo.get_plan_item_by_id(image_item_b.id)
    assert refreshed_a.generation_job_id == result.new_job_id
    assert refreshed_b.generation_job_id == result.new_job_id
    assert refreshed_a.brief_text == "A different background scene entirely."
    assert refreshed_b.brief_text == "A different background scene entirely."

    # The unrelated text item, never linked to the shared job, is untouched.
    unrelated = await marketing_repo.get_plan_item_by_id(text_item.id)
    assert unrelated.generation_job_id is None


async def test_regenerate_requires_job_awaiting_review(db_session: AsyncSession) -> None:
    from fastapi import HTTPException

    ctx = await _seed_workspace(db_session)
    seeded = await _seed_awaiting_review_job(db_session, ctx)
    creation_repo = CreationRepository(db_session)
    await creation_repo.update_job_status(seeded["job"], "approved")
    await db_session.commit()

    with pytest.raises(HTTPException) as exc_info:
        await regenerate_generation_job(
            job_id=seeded["job"].id,
            body=RegenerateJobRequest(brief_text="try again"),
            current_user=ctx["user"],
            context=_context(ctx),
            session=db_session,
            temporal=_FakeTemporalClient(),
        )
    assert exc_info.value.status_code == 409
