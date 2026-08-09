import uuid
from datetime import UTC, datetime
from decimal import Decimal

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from content_studio.db.seed import (
    ensure_default_metric_definitions,
    ensure_default_strategy_version,
)
from content_studio.modules.analytics.exceptions import InsufficientData
from content_studio.modules.analytics.ingestion_service import MetricsIngestionService
from content_studio.modules.analytics.recommendation_engine import RecommendationEngine
from content_studio.modules.analytics.repository import AnalyticsRepository
from content_studio.modules.billing.repository import BillingRepository
from content_studio.modules.billing.service import LedgerService
from content_studio.modules.creation.generation_service import GenerationService
from content_studio.modules.creation.repository import CreationRepository
from content_studio.modules.identity.service import IdentityService
from content_studio.modules.marketing.repository import MarketingRepository
from content_studio.modules.marketing.service import MarketingService
from content_studio.modules.publishing.repository import PublishingRepository
from content_studio.modules.publishing.service import PublishingService
from tests.fakes.ai_image import FakeAIImage
from tests.fakes.ai_text import FakeAIText
from tests.fakes.object_storage import FakeObjectStorage
from tests.fakes.secrets import FakeSecrets
from tests.fakes.social_platform import FakeSocialPlatform

pytestmark = pytest.mark.asyncio


async def _seed_workspace(session: AsyncSession, *, allowance: Decimal = Decimal(100)) -> dict:
    identity = IdentityService(session)
    email = f"ana-{uuid.uuid4().hex[:12]}@example.com"
    signup = await identity.signup(
        email=email, password="correct-horse-battery", display_name="Analytics Test", organization_name="Ana Org"
    )

    billing_repo = BillingRepository(session)
    plan_slug = f"plan-{uuid.uuid4().hex[:8]}"
    plan = await billing_repo.create_plan(
        name=plan_slug, slug=plan_slug, monthly_price=Decimal("39.00"), monthly_credit_allowance=allowance
    )
    await session.commit()

    ledger = LedgerService(session)
    subscription_id = await ledger.open_subscription(organization_id=signup.organization.id, plan_slug=plan.slug)

    marketing_repo = MarketingRepository(session)
    goal = await marketing_repo.get_goal_by_slug("brand_awareness")
    if goal is None:
        goal = await marketing_repo.create_goal(
            slug="brand_awareness", label="Brand awareness", description="Get more people to know you"
        )
    await session.commit()

    await ensure_default_metric_definitions(session)
    await ensure_default_strategy_version(session)

    return {
        "organization_id": signup.organization.id,
        "workspace_id": signup.workspace.id,
        "user_id": signup.user.id,
        "subscription_id": subscription_id,
        "goal_slug": goal.slug,
    }


async def _seed_approved_text_item(session: AsyncSession, ctx: dict) -> uuid.UUID:
    repo = CreationRepository(session)
    recipe = await repo.create_recipe(
        name=f"recipe-{uuid.uuid4().hex[:8]}", content_type="text", provider="openrouter", model="test-model",
        estimated_cost=Decimal("0.5"),
    )
    item = await repo.create_content_item(
        organization_id=ctx["organization_id"], workspace_id=ctx["workspace_id"],
        created_by_user_id=ctx["user_id"], content_type="text", title="Launch announcement",
    )
    job = await repo.create_generation_job(
        organization_id=ctx["organization_id"], workspace_id=ctx["workspace_id"], content_item_id=item.id,
        recipe_id=recipe.id, requested_by_user_id=ctx["user_id"], subscription_id=ctx["subscription_id"],
        brief_text="Announce our new product launch",
    )
    await session.commit()

    gen_service = GenerationService(
        session, ai_text=FakeAIText(fixed_response="Our new product is here!"), ai_image=FakeAIImage(),
        object_storage=FakeObjectStorage(),
    )
    await gen_service.reserve_cost(job.id)
    dispatch_result = await gen_service.dispatch(job.id)
    await gen_service.run_quality_gate(job.id, uuid.UUID(dispatch_result.revision_id))
    await gen_service.finalize_approved(job.id, uuid.UUID(dispatch_result.revision_id), ctx["user_id"], "ship it")

    return item.id


async def _seed_published_attempt(
    session: AsyncSession, ctx: dict, *, secrets: FakeSecrets, platform_adapter: FakeSocialPlatform
) -> dict:
    """Runs the real Phase 3 publish lifecycle so ingestion has a genuine
    PublicationAttempt with an external_post_id to work from."""
    item_id = await _seed_approved_text_item(session, ctx)
    pub_service = PublishingService(
        session, platform_adapter=platform_adapter, secrets=secrets, object_storage=FakeObjectStorage()
    )
    connection = await pub_service.connect_platform(
        organization_id=ctx["organization_id"], workspace_id=ctx["workspace_id"], user_id=ctx["user_id"],
        platform="facebook", code="fake-code",
    )
    pub_repo = PublishingRepository(session)
    plan = await pub_repo.create_publication_plan(
        organization_id=ctx["organization_id"], workspace_id=ctx["workspace_id"], content_item_id=item_id,
        platform_connection_id=connection.id, created_by_user_id=ctx["user_id"], scheduled_for=None,
    )
    await session.commit()
    assert (await pub_service.check_capability(plan.id)).ok
    await pub_service.mark_approved(plan.id, ctx["user_id"])
    dispatch_result = await pub_service.dispatch_publish(plan.id)
    assert dispatch_result.ok
    return {"plan_id": plan.id, "attempt_id": uuid.UUID(dispatch_result.attempt_id)}


async def _seed_campaign_with_plan_item(
    session: AsyncSession, ctx: dict, *, platform: str = "facebook"
) -> tuple[uuid.UUID, uuid.UUID]:
    """Returns a CampaignPlanItem id belonging to a freshly approved
    campaign — enough to attach MetricSnapshots to for comparison tests,
    without needing a full publish lifecycle per item."""
    marketing_service = MarketingService(session)
    brief = await marketing_service.create_brief(
        organization_id=ctx["organization_id"], workspace_id=ctx["workspace_id"], user_id=ctx["user_id"],
        goal_slug=ctx["goal_slug"], what_to_promote="a campaign for comparison", mode="guided",
        target_platforms=[platform],
    )
    proposal = await marketing_service.generate_proposal(brief.id)
    campaign = await marketing_service.approve_proposal(
        proposal_id=proposal.id, user_id=ctx["user_id"], campaign_name=f"Campaign {uuid.uuid4().hex[:6]}"
    )
    marketing_repo = MarketingRepository(session)
    items = await marketing_repo.list_plan_items_for_campaign(campaign.id)
    return campaign.id, items[0].id


async def test_ingest_creates_dual_storage_snapshots_and_links_campaign_item(db_session: AsyncSession) -> None:
    ctx = await _seed_workspace(db_session)
    secrets = FakeSecrets()
    raw_metrics = {"impressions": 1000, "likes": 50, "comments": 10, "shares": 5, "link_clicks": 20}
    platform_adapter = FakeSocialPlatform(post_metrics=raw_metrics)

    published = await _seed_published_attempt(db_session, ctx, secrets=secrets, platform_adapter=platform_adapter)

    _campaign_id, plan_item_id = await _seed_campaign_with_plan_item(db_session, ctx)
    marketing_repo = MarketingRepository(db_session)
    plan_item = await marketing_repo.get_plan_item_by_id(plan_item_id)
    await marketing_repo.link_plan_item_publication(plan_item, publication_plan_id=published["plan_id"])
    await db_session.commit()

    ingestion = MetricsIngestionService(
        db_session, secrets=secrets, platform_adapter_factory=lambda platform: platform_adapter
    )
    snapshots = await ingestion.ingest_for_attempt(published["attempt_id"])

    by_metric: dict[str, object] = {}
    analytics_repo = AnalyticsRepository(db_session)
    for snap in snapshots:
        definition = await analytics_repo.get_metric_definition_by_id(snap.metric_definition_id)
        by_metric[definition.name] = snap

    assert by_metric["impressions"].normalized_value == Decimal(1000)
    assert by_metric["likes"].normalized_value == Decimal(50)
    assert by_metric["engagement_total"].normalized_value == Decimal(65)
    assert by_metric["engagement_rate"].normalized_value == Decimal("0.065000")
    assert by_metric["impressions"].raw_payload == raw_metrics
    assert by_metric["impressions"].publication_attempt_id == published["attempt_id"]
    assert by_metric["impressions"].campaign_plan_item_id == plan_item_id


async def test_ingest_is_append_only_across_repeated_calls(db_session: AsyncSession) -> None:
    ctx = await _seed_workspace(db_session)
    secrets = FakeSecrets()
    platform_adapter = FakeSocialPlatform(post_metrics={"impressions": 500, "likes": 25, "comments": 0, "shares": 0})
    published = await _seed_published_attempt(db_session, ctx, secrets=secrets, platform_adapter=platform_adapter)

    ingestion = MetricsIngestionService(
        db_session, secrets=secrets, platform_adapter_factory=lambda platform: platform_adapter
    )
    first = await ingestion.ingest_for_attempt(published["attempt_id"])
    second = await ingestion.ingest_for_attempt(published["attempt_id"])

    analytics_repo = AnalyticsRepository(db_session)
    all_snapshots = await analytics_repo.list_snapshots_for_attempt(published["attempt_id"])
    assert len(all_snapshots) == len(first) + len(second)


async def test_best_posting_time_raises_insufficient_data_with_no_snapshots(db_session: AsyncSession) -> None:
    ctx = await _seed_workspace(db_session)
    engine = RecommendationEngine(db_session)

    with pytest.raises(InsufficientData):
        await engine.generate_best_posting_time(
            organization_id=ctx["organization_id"], workspace_id=ctx["workspace_id"]
        )


async def test_best_posting_time_picks_highest_bucket_with_medium_confidence(db_session: AsyncSession) -> None:
    ctx = await _seed_workspace(db_session)
    analytics_repo = AnalyticsRepository(db_session)
    definition = await analytics_repo.get_metric_definition_by_name("engagement_rate")

    async def _snapshot(hour: int, value: str) -> None:
        await analytics_repo.create_metric_snapshot(
            organization_id=ctx["organization_id"], workspace_id=ctx["workspace_id"],
            metric_definition_id=definition.id, raw_provider_name="facebook", raw_payload={},
            normalized_value=Decimal(value),
            measurement_time=datetime.now(UTC).replace(hour=hour, minute=0, second=0, microsecond=0),
            collection_time=datetime.now(UTC),
        )

    # Evening (17-23) samples score higher than morning (5-11) samples.
    await _snapshot(20, "0.12")
    await _snapshot(21, "0.10")
    await _snapshot(19, "0.11")
    await _snapshot(9, "0.02")
    await _snapshot(10, "0.03")
    await db_session.commit()

    engine = RecommendationEngine(db_session)
    recommendation = await engine.generate_best_posting_time(
        organization_id=ctx["organization_id"], workspace_id=ctx["workspace_id"]
    )

    assert recommendation.evidence["best_bucket"] == "evening"
    assert recommendation.sample_size == 5
    assert recommendation.confidence == "medium"
    assert "caused" not in recommendation.explanation.lower()


async def test_best_posting_time_reports_low_confidence_with_few_samples(db_session: AsyncSession) -> None:
    ctx = await _seed_workspace(db_session)
    analytics_repo = AnalyticsRepository(db_session)
    definition = await analytics_repo.get_metric_definition_by_name("engagement_rate")

    for hour, value in [(9, "0.05"), (10, "0.04")]:
        await analytics_repo.create_metric_snapshot(
            organization_id=ctx["organization_id"], workspace_id=ctx["workspace_id"],
            metric_definition_id=definition.id, raw_provider_name="facebook", raw_payload={},
            normalized_value=Decimal(value),
            measurement_time=datetime.now(UTC).replace(hour=hour, minute=0, second=0, microsecond=0),
            collection_time=datetime.now(UTC),
        )
    await db_session.commit()

    engine = RecommendationEngine(db_session)
    recommendation = await engine.generate_best_posting_time(
        organization_id=ctx["organization_id"], workspace_id=ctx["workspace_id"]
    )

    assert recommendation.confidence == "low"
    assert "low" in recommendation.explanation.lower()


async def _attach_snapshots(
    session: AsyncSession, ctx: dict, plan_item_id: uuid.UUID, definition_id: uuid.UUID, values: list[str]
) -> None:
    repo = AnalyticsRepository(session)
    for value in values:
        await repo.create_metric_snapshot(
            organization_id=ctx["organization_id"], workspace_id=ctx["workspace_id"],
            metric_definition_id=definition_id, raw_provider_name="facebook", raw_payload={},
            normalized_value=Decimal(value), measurement_time=datetime.now(UTC),
            collection_time=datetime.now(UTC), campaign_plan_item_id=plan_item_id,
        )
    await session.commit()


async def test_campaign_comparison_inconclusive_with_insufficient_samples(db_session: AsyncSession) -> None:
    ctx = await _seed_workspace(db_session)
    analytics_repo = AnalyticsRepository(db_session)
    definition = await analytics_repo.get_metric_definition_by_name("engagement_rate")

    campaign_a_id, item_a = await _seed_campaign_with_plan_item(db_session, ctx)
    campaign_b_id, item_b = await _seed_campaign_with_plan_item(db_session, ctx)
    await _attach_snapshots(db_session, ctx, item_a, definition.id, ["0.10", "0.11"])
    await _attach_snapshots(db_session, ctx, item_b, definition.id, ["0.20", "0.21", "0.19"])

    engine = RecommendationEngine(db_session)
    experiment = await engine.generate_campaign_comparison(
        organization_id=ctx["organization_id"], workspace_id=ctx["workspace_id"], name="A vs B",
        campaign_a_id=campaign_a_id, campaign_b_id=campaign_b_id,
    )

    assert experiment.winner == "inconclusive"
    assert "not enough data" in experiment.result_summary.lower()


async def test_campaign_comparison_declares_winner_with_clear_margin(db_session: AsyncSession) -> None:
    ctx = await _seed_workspace(db_session)
    analytics_repo = AnalyticsRepository(db_session)
    definition = await analytics_repo.get_metric_definition_by_name("engagement_rate")

    campaign_a_id, item_a = await _seed_campaign_with_plan_item(db_session, ctx)
    campaign_b_id, item_b = await _seed_campaign_with_plan_item(db_session, ctx)
    await _attach_snapshots(db_session, ctx, item_a, definition.id, ["0.10", "0.11", "0.09"])
    await _attach_snapshots(db_session, ctx, item_b, definition.id, ["0.20", "0.21", "0.19"])

    engine = RecommendationEngine(db_session)
    experiment = await engine.generate_campaign_comparison(
        organization_id=ctx["organization_id"], workspace_id=ctx["workspace_id"], name="A vs B",
        campaign_a_id=campaign_a_id, campaign_b_id=campaign_b_id,
    )

    assert experiment.winner == "b"
    assert "caused" not in experiment.result_summary.lower()
    assert experiment.evidence["campaign_a"]["sample_size"] == 3
    assert experiment.evidence["campaign_b"]["sample_size"] == 3


async def test_campaign_comparison_inconclusive_when_too_close(db_session: AsyncSession) -> None:
    ctx = await _seed_workspace(db_session)
    analytics_repo = AnalyticsRepository(db_session)
    definition = await analytics_repo.get_metric_definition_by_name("engagement_rate")

    campaign_a_id, item_a = await _seed_campaign_with_plan_item(db_session, ctx)
    campaign_b_id, item_b = await _seed_campaign_with_plan_item(db_session, ctx)
    await _attach_snapshots(db_session, ctx, item_a, definition.id, ["0.100", "0.101", "0.099"])
    await _attach_snapshots(db_session, ctx, item_b, definition.id, ["0.102", "0.103", "0.101"])

    engine = RecommendationEngine(db_session)
    experiment = await engine.generate_campaign_comparison(
        organization_id=ctx["organization_id"], workspace_id=ctx["workspace_id"], name="A vs B",
        campaign_a_id=campaign_a_id, campaign_b_id=campaign_b_id,
    )

    assert experiment.winner == "inconclusive"
    assert "too close" in experiment.result_summary.lower()


async def test_recommendation_outcome_round_trip(db_session: AsyncSession) -> None:
    ctx = await _seed_workspace(db_session)
    analytics_repo = AnalyticsRepository(db_session)
    definition = await analytics_repo.get_metric_definition_by_name("engagement_rate")
    await analytics_repo.create_metric_snapshot(
        organization_id=ctx["organization_id"], workspace_id=ctx["workspace_id"],
        metric_definition_id=definition.id, raw_provider_name="facebook", raw_payload={},
        normalized_value=Decimal("0.08"), measurement_time=datetime.now(UTC),
        collection_time=datetime.now(UTC),
    )
    await db_session.commit()

    engine = RecommendationEngine(db_session)
    recommendation = await engine.generate_best_posting_time(
        organization_id=ctx["organization_id"], workspace_id=ctx["workspace_id"]
    )

    outcome = await analytics_repo.create_recommendation_outcome(
        recommendation_id=recommendation.id, outcome="acted_on", recorded_at=datetime.now(UTC),
        user_id=ctx["user_id"], notes="Scheduled next week's posts for the evening window",
    )
    await db_session.commit()

    outcomes = await analytics_repo.list_outcomes_for_recommendation(recommendation.id)
    assert len(outcomes) == 1
    assert outcomes[0].outcome == "acted_on"
    assert outcomes[0].id == outcome.id
