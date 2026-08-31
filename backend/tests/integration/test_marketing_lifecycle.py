import uuid
from decimal import Decimal

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from content_studio.adapters.policy.opa import OPAPolicyAdapter
from content_studio.config import get_settings
from content_studio.modules.billing.repository import BillingRepository
from content_studio.modules.billing.service import LedgerService
from content_studio.modules.creation.repository import CreationRepository
from content_studio.modules.identity.service import IdentityService
from content_studio.modules.marketing.autopilot_service import AutoPilotService
from content_studio.modules.marketing.repository import MarketingRepository
from content_studio.modules.marketing.service import MarketingService
from content_studio.ports.social_platform import CapabilityResult
from tests.fakes.ai_image import FakeAIImage
from tests.fakes.ai_text import FakeAIText
from tests.fakes.object_storage import FakeObjectStorage
from tests.fakes.secrets import FakeSecrets
from tests.fakes.social_platform import FakeSocialPlatform

pytestmark = pytest.mark.asyncio


async def _seed_workspace(session: AsyncSession, *, allowance: Decimal = Decimal(100)) -> dict:
    identity = IdentityService(session)
    email = f"mkt-{uuid.uuid4().hex[:12]}@example.com"
    signup = await identity.signup(
        email=email, password="correct-horse-battery", display_name="Marketing Test", organization_name="Mkt Org"
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
    await creation_repo.create_recipe(
        name=f"text-recipe-{uuid.uuid4().hex[:8]}", content_type="text", provider="openrouter", model="test-model",
        estimated_cost=Decimal("0.5"),
    )
    await session.commit()

    # MarketingGoal.slug has a CHECK constraint restricting it to the fixed
    # 10-goal catalog (GOAL_SLUGS) — reuse a real one rather than a random
    # test-scoped value, and make it idempotent since the goals table is a
    # shared catalog, not per-test data.
    marketing_repo = MarketingRepository(session)
    goal = await marketing_repo.get_goal_by_slug("brand_awareness")
    if goal is None:
        goal = await marketing_repo.create_goal(
            slug="brand_awareness", label="Brand awareness", description="Get more people to know you"
        )
    await session.commit()

    return {
        "organization_id": signup.organization.id,
        "workspace_id": signup.workspace.id,
        "user_id": signup.user.id,
        "subscription_id": subscription_id,
        "goal_slug": goal.slug,
    }


async def test_generate_proposal_from_brief(db_session: AsyncSession) -> None:
    ctx = await _seed_workspace(db_session)
    service = MarketingService(db_session)

    brief = await service.create_brief(
        organization_id=ctx["organization_id"], workspace_id=ctx["workspace_id"], user_id=ctx["user_id"],
        goal_slug=ctx["goal_slug"], what_to_promote="our summer sale", mode="guided",
        target_platforms=["facebook", "instagram"],
    )
    proposal = await service.generate_proposal(brief.id)

    assert proposal.status == "draft"
    assert len(proposal.plan_items_draft) == 2
    assert proposal.estimated_cost == Decimal("1.0000")
    assert "summer sale" in proposal.objective


async def test_approve_proposal_creates_campaign_and_plan_items(db_session: AsyncSession) -> None:
    ctx = await _seed_workspace(db_session)
    service = MarketingService(db_session)

    brief = await service.create_brief(
        organization_id=ctx["organization_id"], workspace_id=ctx["workspace_id"], user_id=ctx["user_id"],
        goal_slug=ctx["goal_slug"], what_to_promote="our new arrivals", mode="guided", target_platforms=["facebook"],
    )
    proposal = await service.generate_proposal(brief.id)

    campaign = await service.approve_proposal(proposal_id=proposal.id, user_id=ctx["user_id"], campaign_name="New Arrivals Push")

    assert campaign.status == "planning"
    assert campaign.total_spent == Decimal("0.0000")

    repo = MarketingRepository(db_session)
    items = await repo.list_plan_items_for_campaign(campaign.id)
    assert len(items) == 1
    assert items[0].target_platform == "facebook"
    assert items[0].status == "pending"

    decisions = await repo.list_decisions_for_campaign(campaign.id)
    assert len(decisions) == 1
    assert decisions[0].decision_type == "proposal_generated"


def _autopilot_service(session, *, policy=None, ai_text=None, platform_adapter=None, secrets=None) -> AutoPilotService:
    # Defaults to the REAL OPA adapter, not FakePolicy — these tests exist
    # specifically to exercise the actual Rego guardrail policy against a
    # live OPA (see infra/opa-policies/autopilot.rego), which a
    # canned-response fake would silently bypass. Known limitation: unlike
    # the rest of this suite, this assumes the docker-compose `opa` service
    # is already running at Settings.opa_url — a CI-portable version would
    # spin up OPA via testcontainers the way conftest.py does for Postgres.
    return AutoPilotService(
        session,
        policy=policy or OPAPolicyAdapter(get_settings()),
        ai_text=ai_text or FakeAIText(fixed_response="Great autopilot copy"),
        ai_image=FakeAIImage(),
        object_storage=FakeObjectStorage(),
        secrets=secrets or FakeSecrets(),
        platform_adapter_factory=lambda _platform: platform_adapter or FakeSocialPlatform(
            capabilities=[CapabilityResult(capability="direct_publish_text", is_available=True)]
        ),
    )


async def _seed_campaign_with_policy(session: AsyncSession, ctx: dict, *, platform: str = "facebook") -> dict:
    service = MarketingService(session)
    brief = await service.create_brief(
        organization_id=ctx["organization_id"], workspace_id=ctx["workspace_id"], user_id=ctx["user_id"],
        goal_slug=ctx["goal_slug"], what_to_promote="our autopilot test", mode="autopilot", target_platforms=[platform],
    )
    proposal = await service.generate_proposal(brief.id)
    campaign = await service.approve_proposal(proposal_id=proposal.id, user_id=ctx["user_id"], campaign_name="Autopilot Campaign")

    repo = MarketingRepository(session)
    policy = await repo.create_autopilot_policy(
        campaign_id=campaign.id, created_by_user_id=ctx["user_id"], allowed_platforms=[platform],
        max_total_spend=Decimal(100), blocked_topics=[], posting_window_start_hour=0, posting_window_end_hour=23,
    )
    items = await repo.list_plan_items_for_campaign(campaign.id)
    return {"campaign": campaign, "policy": policy, "plan_item": items[0]}


async def test_guardrail_check_allows_when_within_policy(db_session: AsyncSession) -> None:
    ctx = await _seed_workspace(db_session)
    setup = await _seed_campaign_with_policy(db_session, ctx)

    service = _autopilot_service(db_session)
    allow, reasons = await service.check_guardrails(setup["campaign"].id, setup["plan_item"].id)
    assert allow
    assert reasons == []


async def test_guardrail_check_denies_when_kill_switch_active(db_session: AsyncSession) -> None:
    ctx = await _seed_workspace(db_session)
    setup = await _seed_campaign_with_policy(db_session, ctx)

    repo = MarketingRepository(db_session)
    await repo.set_kill_switch(setup["policy"], True)
    await db_session.commit()

    service = _autopilot_service(db_session)
    allow, reasons = await service.check_guardrails(setup["campaign"].id, setup["plan_item"].id)
    assert not allow
    assert any("kill switch" in r for r in reasons)


async def test_guardrail_check_denies_disallowed_platform(db_session: AsyncSession) -> None:
    ctx = await _seed_workspace(db_session)
    setup = await _seed_campaign_with_policy(db_session, ctx, platform="tiktok")

    # Policy only allows "tiktok" from setup, now narrow it to something else
    setup["policy"].allowed_platforms = ["facebook"]
    await db_session.commit()

    service = _autopilot_service(db_session)
    allow, reasons = await service.check_guardrails(setup["campaign"].id, setup["plan_item"].id)
    assert not allow
    assert any("not in the allowed platform list" in r for r in reasons)


async def test_run_item_end_to_end_publishes_when_guardrails_pass(db_session: AsyncSession) -> None:
    ctx = await _seed_workspace(db_session)
    setup = await _seed_campaign_with_policy(db_session, ctx)

    # Connect a facebook account first, matching the plan item's target platform.
    platform_adapter = FakeSocialPlatform(
        capabilities=[CapabilityResult(capability="direct_publish_text", is_available=True)]
    )
    from content_studio.modules.publishing.service import PublishingService

    # Shared FakeSecrets instance: the token sealed during connect_platform
    # must be findable later when the autopilot service unseals it to
    # dispatch the publish — two separate fakes would each have their own
    # empty store, exactly the "no provider key ever stored in plaintext"
    # architecture working as intended (the token only exists via the
    # secrets port), just misapplied to two unrelated fake instances.
    shared_secrets = FakeSecrets()
    pub_service = PublishingService(
        db_session, platform_adapter=platform_adapter, secrets=shared_secrets, object_storage=FakeObjectStorage()
    )
    await pub_service.connect_platform(
        organization_id=ctx["organization_id"], workspace_id=ctx["workspace_id"], user_id=ctx["user_id"],
        platform="facebook", code="fake-code",
    )

    service = _autopilot_service(db_session, platform_adapter=platform_adapter, secrets=shared_secrets)
    result = await service.run_item(setup["campaign"].id, setup["plan_item"].id)

    assert result.proceeded
    assert result.published
    assert result.reasons == []

    repo = MarketingRepository(db_session)
    item = await repo.get_plan_item_by_id(setup["plan_item"].id)
    assert item.status == "published"
    assert item.content_item_id is not None
    assert item.publication_plan_id is not None

    campaign = await repo.get_campaign_by_id(setup["campaign"].id)
    assert campaign.total_spent == Decimal("0.5000")

    decisions = await repo.list_decisions_for_campaign(setup["campaign"].id)
    assert any(d.decision_type == "autopilot_proceed" for d in decisions)


async def test_effective_plan_item_status_reads_through_stale_generating_items(db_session: AsyncSession) -> None:
    """Regression test for the Guided/bulk dispatch path: campaign_plan_items.status
    is written once ("generating") at dispatch time and never updated again outside
    Auto-Pilot's own code path, so a "generating" item can be done already. This
    proves get_effective_plan_item_statuses() reads through to the real
    GenerationJob state instead of trusting the stale stored value."""
    ctx = await _seed_workspace(db_session)
    service = MarketingService(db_session)
    marketing_repo = MarketingRepository(db_session)
    creation_repo = CreationRepository(db_session)

    brief = await service.create_brief(
        organization_id=ctx["organization_id"], workspace_id=ctx["workspace_id"], user_id=ctx["user_id"],
        goal_slug=ctx["goal_slug"], what_to_promote="status sync test", mode="guided", target_platforms=["facebook"],
    )
    proposal = await service.generate_proposal(brief.id)
    campaign = await service.approve_proposal(proposal_id=proposal.id, user_id=ctx["user_id"], campaign_name="Status Sync")
    plan_item = (await marketing_repo.list_plan_items_for_campaign(campaign.id))[0]

    # Mirrors what start_plan_item()/the bulk endpoint actually do: prepare
    # the ContentItem, create a GenerationJob, link it, mark "generating".
    prepared = await service.prepare_item_generation(plan_item)
    job = await creation_repo.create_generation_job(
        organization_id=ctx["organization_id"], workspace_id=ctx["workspace_id"],
        content_item_id=prepared.content_item_id, recipe_id=prepared.recipe_id,
        requested_by_user_id=ctx["user_id"], subscription_id=ctx["subscription_id"], brief_text=prepared.brief_text,
    )
    await marketing_repo.link_plan_item_generation(plan_item, content_item_id=prepared.content_item_id, generation_job_id=job.id)
    await marketing_repo.update_plan_item_status(plan_item, "generating")
    await db_session.commit()

    # Still actually generating — no override, stays "generating".
    statuses = await service.get_effective_plan_item_statuses([plan_item])
    assert statuses[plan_item.id] == "generating"

    # The job finishes generating and clears quality gate — exactly what's
    # missing from /campaigns today: the plan item never hears about it.
    await creation_repo.update_job_status(job, "awaiting_review")
    await db_session.commit()
    statuses = await service.get_effective_plan_item_statuses([plan_item])
    assert statuses[plan_item.id] == "awaiting_review"
    # And the stored value itself is untouched — this is a read-time
    # projection, not a write, deliberately safe against in-flight
    # Temporal workflow executions.
    assert (await marketing_repo.get_plan_item_by_id(plan_item.id)).status == "generating"

    # A hard failure maps to "failed".
    await creation_repo.update_job_status(job, "failed", failure_reason="provider error")
    await db_session.commit()
    statuses = await service.get_effective_plan_item_statuses([plan_item])
    assert statuses[plan_item.id] == "failed"


async def test_run_item_skips_and_records_decision_when_denied(db_session: AsyncSession) -> None:
    ctx = await _seed_workspace(db_session)
    setup = await _seed_campaign_with_policy(db_session, ctx)
    repo = MarketingRepository(db_session)
    await repo.set_kill_switch(setup["policy"], True)
    await db_session.commit()

    service = _autopilot_service(db_session)
    result = await service.run_item(setup["campaign"].id, setup["plan_item"].id)

    assert not result.proceeded
    assert not result.published
    assert any("kill switch" in r for r in result.reasons)

    item = await repo.get_plan_item_by_id(setup["plan_item"].id)
    assert item.status == "skipped"

    decisions = await repo.list_decisions_for_campaign(setup["campaign"].id)
    assert any(d.decision_type == "autopilot_skipped" for d in decisions)

    campaign = await repo.get_campaign_by_id(setup["campaign"].id)
    assert campaign.total_spent == Decimal("0.0000")  # nothing was spent
