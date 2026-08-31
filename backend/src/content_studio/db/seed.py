from decimal import Decimal

from sqlalchemy.ext.asyncio import AsyncSession

from content_studio.config import get_settings
from content_studio.mcp.tools import (
    GENERATE_BEST_POSTING_TIME_TOOL,
    GENERATE_BEST_POSTING_TIME_VERSION,
    GENERATE_PRODUCT_CAMPAIGN_TOOL,
    GENERATE_PRODUCT_CAMPAIGN_VERSION,
)
from content_studio.modules.analytics.recommendation_engine import DEFAULT_STRATEGY_VERSION_NAME
from content_studio.modules.analytics.repository import AnalyticsRepository
from content_studio.modules.billing.repository import BillingRepository
from content_studio.modules.creation.repository import CreationRepository
from content_studio.modules.governance.repository import GovernanceRepository
from content_studio.modules.marketing.repository import MarketingRepository

DEFAULT_PLAN_SLUG = "starter"

# The 8 named agents from 15_MCP_AGENTS_AND_SECURITY.md — 'formalizing'
# them means each gets a real catalog row here, not just a name in a spec
# document. Not every agent has a fully-implemented MCP tool yet (see
# ensure_default_tools) — the catalog is complete, the tool set grows
# incrementally, same precedent as ModelVersion staying dormant until it's
# genuinely ready.
_AGENTS = [
    ("marketing_manager", "Marketing Manager Agent", "marketing", "Plans marketing briefs and generates campaign proposals."),
    ("campaign_planner", "Campaign Planner Agent", "planning", "Plans campaign structure, sequencing, and scheduling."),
    ("creation_coordinator", "Creation Coordinator Agent", "generation", "Coordinates AI content generation across text, image, and audio."),
    ("publishing", "Publishing Agent", "publishing", "Schedules and dispatches approved content to connected platforms."),
    ("analytics_recommendation", "Analytics/Recommendation Agent", "analytics", "Generates deterministic, data-backed recommendations."),
    ("ecommerce", "eCommerce Agent", "commerce", "Generates product-aware campaigns from synced store catalogs."),
    ("audio_guide", "Audio Guide Agent", "audio", "Guides audio content creation - voiceover, music, and soundscapes."),
    ("support", "Support Agent", "support", "Handles support cases and moderation escalations."),
]

# The normalized metric vocabulary every provider's raw post-metric field
# gets mapped onto (see analytics/ingestion_service.py's _RAW_FIELD_TO_METRIC).
_METRIC_DEFINITIONS = [
    ("impressions", "count", "post", "Number of times a post was shown (provider-reported reach/impressions/views)."),
    ("likes", "count", "post", "Number of like/reaction-equivalent interactions on a post."),
    ("comments", "count", "post", "Number of comments on a post."),
    ("shares", "count", "post", "Number of shares/reposts of a post."),
    ("link_clicks", "count", "post", "Number of clicks on a link attached to a post."),
    ("engagement_total", "count", "post", "Sum of likes, comments, and shares on a post."),
    ("engagement_rate", "ratio", "post", "Engagement total divided by impressions for a post."),
    ("avg_view_duration_seconds", "seconds", "post", "Average watch duration for a video post."),
]

_MARKETING_GOALS = [
    ("more_sales", "More sales", "Drive more purchases or revenue for your products or services."),
    ("more_messages_bookings", "More messages or bookings", "Get more people to message you or book an appointment."),
    ("more_website_traffic", "More website traffic", "Send more visitors to your website or store."),
    ("more_followers_engagement", "More followers and engagement", "Grow your audience and get more likes, comments, and shares."),
    ("brand_awareness", "Brand awareness", "Help more people discover and recognize your brand."),
    ("product_service_launch", "Product or service launch", "Announce something new you're offering."),
    ("offer_announcement", "Offer announcement", "Promote a sale, discount, or limited-time offer."),
    ("product_education", "Product education", "Help your audience understand what you offer and why it matters."),
    ("retargeting", "Retargeting", "Re-engage people who've already shown interest."),
    ("seasonal_evergreen_promotion", "Seasonal or evergreen promotion", "Promote something tied to a season or that works year-round."),
]


async def ensure_default_plans(session: AsyncSession) -> None:
    """Idempotent seed for the plan catalog. Draft pricing per
    22_BILLING_AND_PRICING_MODEL.md — configurable, not final."""
    repo = BillingRepository(session)
    existing = await repo.get_plan_by_slug(DEFAULT_PLAN_SLUG)
    if existing is not None:
        return

    await repo.create_plan(
        name="Starter",
        slug=DEFAULT_PLAN_SLUG,
        monthly_price=Decimal("39.00"),
        monthly_credit_allowance=Decimal(500),
        currency="EUR",
    )
    await session.commit()


async def ensure_default_marketing_goals(session: AsyncSession) -> None:
    """Idempotent seed for the 10-goal catalog from
    07_AI_MARKETING_MANAGER_MODULE.md."""
    repo = MarketingRepository(session)
    for slug, label, description in _MARKETING_GOALS:
        if await repo.get_goal_by_slug(slug) is None:
            await repo.create_goal(slug=slug, label=label, description=description)
    await session.commit()


async def ensure_default_content_recipes(session: AsyncSession) -> None:
    """Idempotent seed for the Phase 2 content recipe catalog — one active
    recipe per supported content_type, so /content/briefs always has
    something to route to."""
    settings = get_settings()
    repo = CreationRepository(session)

    if await repo.get_active_recipe_for_content_type("text") is None:
        await repo.create_recipe(
            name="social_caption_text",
            content_type="text",
            provider="openrouter",
            model=settings.ai_text_default_model,
            estimated_cost=Decimal("0.50"),
            params={"max_tokens": 400, "temperature": 0.7},
        )

    if await repo.get_active_recipe_for_content_type("image") is None:
        await repo.create_recipe(
            name="product_image",
            content_type="image",
            provider="replicate",
            model=settings.ai_image_default_model,
            estimated_cost=Decimal("0.08"),
            params={},
        )

    if await repo.get_active_recipe_for_content_type("audio") is None:
        await repo.create_recipe(
            name="voiceover_audio",
            content_type="audio",
            provider="replicate",
            model=settings.ai_audio_default_model,
            estimated_cost=Decimal("1.50"),
            params={},
        )

    await session.commit()


async def ensure_default_metric_definitions(session: AsyncSession) -> None:
    """Idempotent seed for the normalized metric catalog every provider's
    raw metric payload gets mapped onto."""
    repo = AnalyticsRepository(session)
    for name, unit, scope, description in _METRIC_DEFINITIONS:
        if await repo.get_metric_definition_by_name(name) is None:
            await repo.create_metric_definition(name=name, unit=unit, scope=scope, description=description)
    await session.commit()


async def ensure_default_strategy_version(session: AsyncSession) -> None:
    """Idempotent seed for the one deterministic/statistical recommendation
    strategy this phase ships — see 09_RECOMMENDATION_ENGINE.md's ML-gating
    rule (recommendation_engine.py's module docstring)."""
    repo = AnalyticsRepository(session)
    if await repo.get_strategy_version_by_name(DEFAULT_STRATEGY_VERSION_NAME) is None:
        await repo.create_strategy_version(
            name=DEFAULT_STRATEGY_VERSION_NAME,
            description="Deterministic, statistical-only recommendations: sample-size-aware aggregates over "
            "real MetricSnapshot data, no ML or predictive models.",
            is_active=True,
        )
    await session.commit()


async def ensure_default_agents(session: AsyncSession) -> None:
    """Idempotent seed for the 8-agent catalog from 15_MCP_AGENTS_AND_SECURITY.md."""
    repo = GovernanceRepository(session)
    for name, display_name, mcp_domain, description in _AGENTS:
        if await repo.get_agent_by_name(name) is None:
            await repo.create_agent(name=name, display_name=display_name, mcp_domain=mcp_domain, description=description)
    await session.commit()


async def ensure_default_tools(session: AsyncSession) -> None:
    """Idempotent seed for the tools this phase actually implements — one
    high-risk/requires-approval example and one low-risk/auto-allowed
    example, so both branches of the OPA policy have a real, registered
    tool exercising them, not just a hypothetical one."""
    repo = GovernanceRepository(session)

    ecommerce_agent = await repo.get_agent_by_name("ecommerce")
    assert ecommerce_agent is not None
    if await repo.get_tool_by_name_version(GENERATE_PRODUCT_CAMPAIGN_TOOL, GENERATE_PRODUCT_CAMPAIGN_VERSION) is None:
        await repo.create_tool(
            agent_id=ecommerce_agent.id, name=GENERATE_PRODUCT_CAMPAIGN_TOOL,
            version=GENERATE_PRODUCT_CAMPAIGN_VERSION, risk_level="high", requires_approval=True,
            description="Generates a marketing campaign proposal from a synced product's title and description. "
            "Creates real campaign records, so it requires an explicit, single-use approval before it runs.",
        )

    analytics_agent = await repo.get_agent_by_name("analytics_recommendation")
    assert analytics_agent is not None
    if await repo.get_tool_by_name_version(GENERATE_BEST_POSTING_TIME_TOOL, GENERATE_BEST_POSTING_TIME_VERSION) is None:
        await repo.create_tool(
            agent_id=analytics_agent.id, name=GENERATE_BEST_POSTING_TIME_TOOL,
            version=GENERATE_BEST_POSTING_TIME_VERSION, risk_level="low", requires_approval=False,
            description="Generates a best-posting-time recommendation from historical engagement data. "
            "Read-only, no approval required.",
        )

    await session.commit()
