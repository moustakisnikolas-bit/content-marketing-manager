import uuid
from decimal import Decimal

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from content_studio.api.deps import WorkspaceContext
from content_studio.api.v1.content import review_generation_job
from content_studio.api.v1.marketing import publish_approved
from content_studio.modules.billing.repository import BillingRepository
from content_studio.modules.billing.service import LedgerService
from content_studio.modules.commerce.repository import CommerceRepository
from content_studio.modules.commerce.service import CommerceService
from content_studio.modules.creation.generation_service import GenerationService
from content_studio.modules.creation.repository import CreationRepository
from content_studio.modules.creation.schemas import ReviewRequest
from content_studio.modules.identity.service import IdentityService
from content_studio.modules.marketing.repository import MarketingRepository
from content_studio.modules.marketing.service import MarketingService
from content_studio.modules.publishing.repository import PublishingRepository
from content_studio.ports.store_connector import ProductData, ProductPage
from content_studio.workflows.publication import PublicationWorkflow
from tests.fakes.ai_image import FakeAIImage
from tests.fakes.ai_text import FakeAIText
from tests.fakes.object_storage import FakeObjectStorage
from tests.fakes.secrets import FakeSecrets
from tests.fakes.store_connector import FakeStoreConnector

pytestmark = pytest.mark.asyncio


class _FakeWorkflowHandle:
    def __init__(self, signals: list) -> None:
        self._signals = signals

    async def signal(self, method, args) -> None:
        self._signals.append((method, args))


class _FakeTemporalClient:
    """Accepts both start_workflow() calling conventions used across this
    codebase: a single positional input (GenerationWorkflow's) and the
    args=[...] list form (PublicationWorkflow's, since it takes two
    positional run() args)."""

    def __init__(self) -> None:
        self.signals: list = []
        self.started: list = []

    def get_workflow_handle(self, workflow_id: str) -> _FakeWorkflowHandle:
        return _FakeWorkflowHandle(self.signals)

    async def start_workflow(self, run_fn, *positional, args=None, id: str, task_queue: str) -> None:
        self.started.append({"id": id, "args": args if args is not None else list(positional)})


async def _seed_workspace(session: AsyncSession, *, allowance: Decimal = Decimal(100)) -> dict:
    identity = IdentityService(session)
    email = f"pubap-{uuid.uuid4().hex[:12]}@example.com"
    signup = await identity.signup(
        email=email, password="correct-horse-battery", display_name="Publish Approved Test",
        organization_name="Publish Approved Org",
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
    await creation_repo.create_recipe(
        name=f"image-recipe-{uuid.uuid4().hex[:8]}", content_type="image", provider="replicate", model="test-model",
        estimated_cost=Decimal("2.0"),
    )
    await session.commit()

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
        "goal_slug": goal.slug,
    }


async def _seed_product(session: AsyncSession, ctx: dict):
    pages = [
        ProductPage(
            products=[
                ProductData(
                    external_product_id="p1", title="Whiskey Caramel 200γρ.", description="A cozy candle",
                    price="10.00", currency="USD", status="active",
                    raw_payload={"permalink": "https://ceri.gr/shop/wax-melts/whiskey-caramel/"},
                    image_urls=["https://example.com/whiskey-caramel.jpg"],
                ),
            ],
            next_cursor=None,
        ),
    ]
    adapter = FakeStoreConnector(pages=pages)
    service = CommerceService(session, secrets=FakeSecrets(), store_adapter_factory=lambda _platform: adapter)
    connection = await service.connect_store(
        organization_id=ctx["organization_id"], workspace_id=ctx["workspace_id"], user_id=ctx["user"].id,
        platform="woocommerce", code="fake-code",
    )
    await service.sync_products(connection.id)
    repo = CommerceRepository(session)
    return (await repo.list_products_for_connection(connection.id))[0]


async def _seed_approved_item(session: AsyncSession, ctx: dict, *, content_type: str, title: str, text_body: str) -> tuple:
    repo = CreationRepository(session)
    recipe = await repo.get_active_recipe_for_content_type(content_type)
    item = await repo.create_content_item(
        organization_id=ctx["organization_id"], workspace_id=ctx["workspace_id"],
        created_by_user_id=ctx["user"].id, content_type=content_type, title=title,
    )
    job = await repo.create_generation_job(
        organization_id=ctx["organization_id"], workspace_id=ctx["workspace_id"], content_item_id=item.id,
        recipe_id=recipe.id, requested_by_user_id=ctx["user"].id, subscription_id=ctx["subscription_id"],
        brief_text=f"Brief for {title}",
    )
    await session.commit()

    gen_service = GenerationService(
        session, ai_text=FakeAIText(fixed_response=text_body), ai_image=FakeAIImage(), object_storage=FakeObjectStorage(),
    )
    await gen_service.reserve_cost(job.id)
    dispatch_result = await gen_service.dispatch(job.id)
    await gen_service.run_quality_gate(job.id, uuid.UUID(dispatch_result.revision_id))
    await gen_service.finalize_approved(job.id, uuid.UUID(dispatch_result.revision_id), ctx["user"].id, "ship it")

    return item, job


def _context(ctx: dict) -> WorkspaceContext:
    return WorkspaceContext(
        organization_id=ctx["organization_id"], workspace_id=ctx["workspace_id"],
        subscription_id=ctx["subscription_id"], role_permissions=[],
    )


async def _seed_campaign_with_pair(
    session: AsyncSession, ctx: dict, *, caption: str = "Cozy nights start here. Light one and relax.",
    connect_platform: bool = True,
):
    """Builds a campaign with one product whose text+image plan items are
    both content-approved (real ContentPackage/revision each) and linked —
    exactly the shape publish_approved() operates on."""
    product = await _seed_product(session, ctx)

    connection = None
    if connect_platform:
        publishing_repo = PublishingRepository(session)
        connection = await publishing_repo.create_connection(
            organization_id=ctx["organization_id"], workspace_id=ctx["workspace_id"],
            connected_by_user_id=ctx["user"].id, platform="instagram", external_account_id="ig-fake-1",
            external_account_name="Fake IG", access_token_secret_ref="sealed-ref", refresh_token_secret_ref=None,
            scopes=[],
        )

    marketing_service = MarketingService(session)
    brief = await marketing_service.create_brief(
        organization_id=ctx["organization_id"], workspace_id=ctx["workspace_id"], user_id=ctx["user"].id,
        goal_slug=ctx["goal_slug"], what_to_promote="whiskey caramel launch", mode="guided",
        target_platforms=["instagram"],
    )
    proposal = await marketing_service.generate_proposal(brief.id)
    campaign = await marketing_service.approve_proposal(
        proposal_id=proposal.id, user_id=ctx["user"].id, campaign_name="Whiskey Caramel Launch"
    )

    text_content_item, text_job = await _seed_approved_item(
        session, ctx, content_type="text", title="Whiskey Caramel (text)", text_body=caption
    )
    image_content_item, image_job = await _seed_approved_item(
        session, ctx, content_type="image", title="Whiskey Caramel (image)", text_body="unused"
    )

    marketing_repo = MarketingRepository(session)
    text_item = await marketing_repo.create_plan_item(
        campaign_id=campaign.id, sequence_number=90, title="Whiskey Caramel (text)", brief_text="n/a",
        target_platform="instagram", product_id=product.id, content_type="text",
    )
    await marketing_repo.link_plan_item_generation(
        text_item, content_item_id=text_content_item.id, generation_job_id=text_job.id
    )
    image_item = await marketing_repo.create_plan_item(
        campaign_id=campaign.id, sequence_number=91, title="Whiskey Caramel (image)", brief_text="n/a",
        target_platform="instagram", product_id=product.id, content_type="image",
    )
    await marketing_repo.link_plan_item_generation(
        image_item, content_item_id=image_content_item.id, generation_job_id=image_job.id
    )
    await session.commit()

    return {
        "campaign": campaign, "product": product, "connection": connection,
        "text_item": text_item, "image_item": image_item,
        "text_content_item": text_content_item, "image_content_item": image_content_item,
    }


async def test_publish_approved_copies_caption_publishes_image_and_creates_story(db_session: AsyncSession) -> None:
    ctx = await _seed_workspace(db_session)
    seeded = await _seed_campaign_with_pair(db_session, ctx, caption="Cozy nights start here. Light one and relax.")
    temporal = _FakeTemporalClient()

    response = await publish_approved(
        campaign_id=seeded["campaign"].id, current_user=ctx["user"], context=_context(ctx),
        session=db_session, temporal=temporal,
    )

    assert response.skipped == []
    assert len(response.published) == 1
    published = response.published[0]
    assert published.product_id == seeded["product"].id
    assert published.plan_item_id == seeded["image_item"].id
    assert published.story_plan_item_id is not None

    creation_repo = CreationRepository(db_session)
    package = await creation_repo.get_package_for_item(seeded["image_content_item"].id)
    image_revision = await creation_repo.get_revision_by_id(package.selected_revision_id)
    assert image_revision.text_body == "Cozy nights start here. Light one and relax."

    marketing_repo = MarketingRepository(db_session)
    refreshed_image_item = await marketing_repo.get_plan_item_by_id(seeded["image_item"].id)
    assert refreshed_image_item.publication_plan_id == published.publication_plan_id

    story_item = await marketing_repo.get_plan_item_by_id(published.story_plan_item_id)
    assert story_item.content_type == "story"
    assert story_item.source_plan_item_id == seeded["image_item"].id
    assert story_item.product_id == seeded["product"].id
    assert story_item.status == "generating"
    assert story_item.generation_job_id is not None

    started_ids = {s["id"] for s in temporal.started}
    assert f"publication-{published.publication_plan_id}" in started_ids
    assert any(sid.startswith("generation-") for sid in started_ids)  # the story's own image generation


async def test_publish_approved_skips_when_no_connected_platform(db_session: AsyncSession) -> None:
    ctx = await _seed_workspace(db_session)
    seeded = await _seed_campaign_with_pair(db_session, ctx, connect_platform=False)

    response = await publish_approved(
        campaign_id=seeded["campaign"].id, current_user=ctx["user"], context=_context(ctx),
        session=db_session, temporal=_FakeTemporalClient(),
    )

    assert response.published == []
    assert len(response.skipped) == 1
    assert "No connected instagram account" in response.skipped[0].reason


async def test_approving_story_item_creates_and_starts_story_publication_plan(db_session: AsyncSession) -> None:
    ctx = await _seed_workspace(db_session)
    seeded = await _seed_campaign_with_pair(db_session, ctx)

    publish_response = await publish_approved(
        campaign_id=seeded["campaign"].id, current_user=ctx["user"], context=_context(ctx),
        session=db_session, temporal=_FakeTemporalClient(),
    )
    story_plan_item_id = publish_response.published[0].story_plan_item_id

    marketing_repo = MarketingRepository(db_session)
    story_item = await marketing_repo.get_plan_item_by_id(story_plan_item_id)
    assert story_item.publication_plan_id is None

    creation_repo = CreationRepository(db_session)
    story_job = await creation_repo.get_generation_job_by_id(story_item.generation_job_id)
    await creation_repo.update_job_status(story_job, "awaiting_review")
    await creation_repo.set_job_workflow_id(story_job, f"generation-{story_job.id}")
    await db_session.commit()

    temporal = _FakeTemporalClient()
    await review_generation_job(
        job_id=story_job.id, body=ReviewRequest(decision="approved", revision_id=uuid.uuid4(), comment=None),
        current_user=ctx["user"], context=_context(ctx), session=db_session, temporal=temporal,
    )

    refreshed_story_item = await marketing_repo.get_plan_item_by_id(story_plan_item_id)
    assert refreshed_story_item.publication_plan_id is not None

    publishing_repo = PublishingRepository(db_session)
    story_plan = await publishing_repo.get_publication_plan_by_id(refreshed_story_item.publication_plan_id)
    assert story_plan.target_format == "story"
    assert f"publication-{story_plan.id}" in {s["id"] for s in temporal.started}
    # Two signals land on this fake client: review_generation_job() itself
    # signals the story's own GenerationWorkflow (the review action), and
    # _maybe_publish_approved_story() then signals the new PublicationWorkflow.
    assert len(temporal.signals) == 2
    publication_signal = next(s for s in temporal.signals if s[0] is PublicationWorkflow.submit_review)
    assert publication_signal[1][0] == "approved"
