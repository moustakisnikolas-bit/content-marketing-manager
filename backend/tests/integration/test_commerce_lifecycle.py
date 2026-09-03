import json
import uuid
from decimal import Decimal

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from content_studio.api.deps import WorkspaceContext
from content_studio.api.v1.commerce import bulk_generate_product_campaign
from content_studio.api.v1.content import edit_revision_text, review_generation_job
from content_studio.modules.billing.repository import BillingRepository
from content_studio.modules.billing.service import LedgerService
from content_studio.modules.commerce.exceptions import ConsentRequired
from content_studio.modules.commerce.repository import CommerceRepository
from content_studio.modules.commerce.schemas import BulkProductCampaignRequest
from content_studio.modules.commerce.service import CommerceService, _strip_product_size
from content_studio.modules.commerce.webhook_signature import compute_signature
from content_studio.modules.creation.repository import CreationRepository
from content_studio.modules.creation.schemas import EditRevisionTextRequest, ReviewRequest
from content_studio.modules.identity.models import User
from content_studio.modules.identity.repository import IdentityRepository
from content_studio.modules.identity.service import IdentityService
from content_studio.modules.marketing.exceptions import CampaignNotFound
from content_studio.modules.marketing.repository import MarketingRepository
from content_studio.modules.publishing.repository import PublishingRepository
from tests.fakes.secrets import FakeSecrets
from tests.fakes.store_connector import FakeStoreConnector

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
    email = f"com-{uuid.uuid4().hex[:12]}@example.com"
    signup = await identity.signup(
        email=email, password="correct-horse-battery", display_name="Commerce Test", organization_name="Com Org"
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

    marketing_repo = MarketingRepository(session)
    goal = await marketing_repo.get_goal_by_slug("brand_awareness")
    if goal is None:
        goal = await marketing_repo.create_goal(
            slug="brand_awareness", label="Brand awareness", description="Get more people to know you"
        )
    retargeting = await marketing_repo.get_goal_by_slug("retargeting")
    if retargeting is None:
        await marketing_repo.create_goal(
            slug="retargeting", label="Retargeting", description="Re-engage people who've already shown interest"
        )
    await session.commit()

    return {
        "organization_id": signup.organization.id,
        "workspace_id": signup.workspace.id,
        "user_id": signup.user.id,
        "subscription_id": subscription_id,
        "goal_slug": goal.slug,
    }


def _service(session: AsyncSession, *, adapter: FakeStoreConnector, secrets: FakeSecrets) -> CommerceService:
    return CommerceService(session, secrets=secrets, store_adapter_factory=lambda platform: adapter)


async def test_connect_store_seals_tokens_and_resolves_capabilities(db_session: AsyncSession) -> None:
    ctx = await _seed_workspace(db_session)
    secrets = FakeSecrets()
    adapter = FakeStoreConnector()
    service = _service(db_session, adapter=adapter, secrets=secrets)

    connection = await service.connect_store(
        organization_id=ctx["organization_id"], workspace_id=ctx["workspace_id"], user_id=ctx["user_id"],
        platform="shopify", code="fake-code",
    )

    assert connection.access_token_secret_ref in secrets.store
    assert connection.webhook_secret_ref in secrets.store
    assert secrets.store[connection.access_token_secret_ref] == "fake-store-access-token"

    repo = CommerceRepository(db_session)
    capabilities = await repo.list_capabilities_for_connection(connection.id)
    names = {c.capability for c in capabilities}
    assert "read_products" in names


async def test_connect_store_with_credentials_seals_tokens(db_session: AsyncSession) -> None:
    ctx = await _seed_workspace(db_session)
    secrets = FakeSecrets()
    adapter = FakeStoreConnector()
    service = _service(db_session, adapter=adapter, secrets=secrets)

    connection = await service.connect_store_with_credentials(
        organization_id=ctx["organization_id"], workspace_id=ctx["workspace_id"], user_id=ctx["user_id"],
        platform="woocommerce", store_domain="https://my-shop.example.com", consumer_key="ck_test",
        consumer_secret="cs_test",
    )

    assert connection.platform == "woocommerce"
    assert connection.store_domain == "https://my-shop.example.com"
    assert connection.access_token_secret_ref in secrets.store
    assert connection.webhook_secret_ref in secrets.store

    repo = CommerceRepository(db_session)
    capabilities = await repo.list_capabilities_for_connection(connection.id)
    assert {c.capability for c in capabilities} == {c.capability for c in adapter.capabilities}


async def test_disconnect_store_deletes_connection_and_secrets(db_session: AsyncSession) -> None:
    ctx = await _seed_workspace(db_session)
    secrets = FakeSecrets()
    adapter = FakeStoreConnector()
    service = _service(db_session, adapter=adapter, secrets=secrets)

    connection = await service.connect_store(
        organization_id=ctx["organization_id"], workspace_id=ctx["workspace_id"], user_id=ctx["user_id"],
        platform="shopify", code="fake-code",
    )
    access_ref, webhook_ref = connection.access_token_secret_ref, connection.webhook_secret_ref
    assert access_ref in secrets.store
    assert webhook_ref in secrets.store

    await service.disconnect_store(connection.id, user_id=ctx["user_id"])

    repo = CommerceRepository(db_session)
    assert await repo.get_connection_by_id(connection.id) is None
    assert access_ref not in secrets.store
    assert webhook_ref not in secrets.store


async def test_disconnect_store_cascade_deletes_products(db_session: AsyncSession) -> None:
    ctx = await _seed_workspace(db_session)
    secrets = FakeSecrets()
    adapter = FakeStoreConnector()
    service = _service(db_session, adapter=adapter, secrets=secrets)

    connection = await service.connect_store(
        organization_id=ctx["organization_id"], workspace_id=ctx["workspace_id"], user_id=ctx["user_id"],
        platform="shopify", code="fake-code",
    )
    await service.sync_products(connection.id)

    repo = CommerceRepository(db_session)
    products_before = await repo.list_products_for_connection(connection.id)
    assert len(products_before) > 0

    await service.disconnect_store(connection.id, user_id=ctx["user_id"])

    products_after = await repo.list_products_for_workspace(ctx["workspace_id"])
    assert products_after == []


async def test_webhook_with_product_topic_triggers_resync(db_session: AsyncSession) -> None:
    ctx = await _seed_workspace(db_session)
    secrets = FakeSecrets()
    adapter = FakeStoreConnector()
    service = _service(db_session, adapter=adapter, secrets=secrets)

    connection = await service.connect_store(
        organization_id=ctx["organization_id"], workspace_id=ctx["workspace_id"], user_id=ctx["user_id"],
        platform="shopify", code="fake-code",
    )

    repo = CommerceRepository(db_session)
    products_before = await repo.list_products_for_connection(connection.id)
    assert products_before == []

    body = json.dumps({"id": "fake-product-1"}).encode()
    signature = compute_signature(body, adapter.webhook_secret)
    result = await service.receive_webhook(
        connection_id=connection.id, topic="product.updated", raw_body=body, signature_header=signature,
        external_delivery_id=None,
    )

    assert result.accepted is True
    # A verified product.* webhook should trigger the same sync_products()
    # flow the "Sync now" button uses — no manual re-sync needed.
    products_after = await repo.list_products_for_connection(connection.id)
    assert len(products_after) == 1


async def test_sync_products_is_idempotent_and_upserts(db_session: AsyncSession) -> None:
    ctx = await _seed_workspace(db_session)
    secrets = FakeSecrets()
    adapter = FakeStoreConnector()
    service = _service(db_session, adapter=adapter, secrets=secrets)

    connection = await service.connect_store(
        organization_id=ctx["organization_id"], workspace_id=ctx["workspace_id"], user_id=ctx["user_id"],
        platform="shopify", code="fake-code",
    )

    first = await service.sync_products(connection.id)
    assert first.products_synced == 1
    second = await service.sync_products(connection.id)
    assert second.products_synced == 1

    repo = CommerceRepository(db_session)
    products = await repo.list_products_for_connection(connection.id)
    # Same external_product_id both times — an upsert, not a duplicate.
    assert len(products) == 1
    assert products[0].title == "Fake Product"

    detail = await repo.get_product_with_details_by_id(products[0].id)
    assert len(detail.variants) == 0
    assert len(detail.assets) == 1


async def test_sync_products_drains_paginated_catalog_without_duplicates(db_session: AsyncSession) -> None:
    from content_studio.ports.store_connector import ProductData, ProductPage

    ctx = await _seed_workspace(db_session)
    secrets = FakeSecrets()
    pages = [
        ProductPage(
            products=[
                ProductData(
                    external_product_id="p1", title="Product 1", description="d1", price="10.00", currency="USD",
                    status="active", raw_payload={},
                )
            ],
            next_cursor="1",
        ),
        ProductPage(
            products=[
                ProductData(
                    external_product_id="p2", title="Product 2", description="d2", price="20.00", currency="USD",
                    status="active", raw_payload={},
                )
            ],
            next_cursor=None,
        ),
    ]
    adapter = FakeStoreConnector(pages=pages)
    service = _service(db_session, adapter=adapter, secrets=secrets)
    connection = await service.connect_store(
        organization_id=ctx["organization_id"], workspace_id=ctx["workspace_id"], user_id=ctx["user_id"],
        platform="woocommerce", code="fake-code",
    )

    result1 = await service.sync_products(connection.id)
    assert result1.next_cursor == "1"
    result2 = await service.sync_products(connection.id)
    assert result2.next_cursor is None

    repo = CommerceRepository(db_session)
    products = await repo.list_products_for_connection(connection.id)
    assert {p.external_product_id for p in products} == {"p1", "p2"}


async def test_webhook_with_valid_signature_is_accepted(db_session: AsyncSession) -> None:
    ctx = await _seed_workspace(db_session)
    secrets = FakeSecrets()
    adapter = FakeStoreConnector(webhook_secret="correct-secret")
    service = _service(db_session, adapter=adapter, secrets=secrets)
    connection = await service.connect_store(
        organization_id=ctx["organization_id"], workspace_id=ctx["workspace_id"], user_id=ctx["user_id"],
        platform="shopify", code="fake-code",
    )

    body = json.dumps({"id": "cart-1"}).encode("utf-8")
    signature = compute_signature(body, "correct-secret")

    result = await service.receive_webhook(
        connection_id=connection.id, topic="products/update", raw_body=body, signature_header=signature,
        external_delivery_id="delivery-1",
    )

    assert result.accepted is True
    repo = CommerceRepository(db_session)
    deliveries = await repo.list_deliveries_for_connection(connection.id)
    assert len(deliveries) == 1
    assert deliveries[0].signature_valid is True
    assert deliveries[0].processed_at is not None


async def test_webhook_with_invalid_signature_is_rejected_and_not_processed(db_session: AsyncSession) -> None:
    ctx = await _seed_workspace(db_session)
    secrets = FakeSecrets()
    adapter = FakeStoreConnector(webhook_secret="correct-secret")
    service = _service(db_session, adapter=adapter, secrets=secrets)
    connection = await service.connect_store(
        organization_id=ctx["organization_id"], workspace_id=ctx["workspace_id"], user_id=ctx["user_id"],
        platform="shopify", code="fake-code",
    )

    body = json.dumps({"id": "cart-1"}).encode("utf-8")
    bogus_signature = compute_signature(body, "wrong-secret")

    result = await service.receive_webhook(
        connection_id=connection.id, topic="products/update", raw_body=body, signature_header=bogus_signature,
        external_delivery_id="delivery-bad",
    )

    assert result.accepted is False
    repo = CommerceRepository(db_session)
    deliveries = await repo.list_deliveries_for_connection(connection.id)
    assert deliveries[0].signature_valid is False
    assert deliveries[0].processed_at is None


async def test_webhook_delivery_is_idempotent_by_external_delivery_id(db_session: AsyncSession) -> None:
    ctx = await _seed_workspace(db_session)
    secrets = FakeSecrets()
    adapter = FakeStoreConnector(webhook_secret="correct-secret")
    service = _service(db_session, adapter=adapter, secrets=secrets)
    connection = await service.connect_store(
        organization_id=ctx["organization_id"], workspace_id=ctx["workspace_id"], user_id=ctx["user_id"],
        platform="shopify", code="fake-code",
    )

    body = json.dumps({"id": "cart-1"}).encode("utf-8")
    signature = compute_signature(body, "correct-secret")

    first = await service.receive_webhook(
        connection_id=connection.id, topic="products/update", raw_body=body, signature_header=signature,
        external_delivery_id="dup-delivery",
    )
    second = await service.receive_webhook(
        connection_id=connection.id, topic="products/update", raw_body=body, signature_header=signature,
        external_delivery_id="dup-delivery",
    )

    assert first.delivery_id == second.delivery_id
    repo = CommerceRepository(db_session)
    deliveries = await repo.list_deliveries_for_connection(connection.id)
    assert len(deliveries) == 1


async def test_generate_product_campaign_references_product(db_session: AsyncSession) -> None:
    ctx = await _seed_workspace(db_session)
    secrets = FakeSecrets()
    adapter = FakeStoreConnector()
    service = _service(db_session, adapter=adapter, secrets=secrets)
    connection = await service.connect_store(
        organization_id=ctx["organization_id"], workspace_id=ctx["workspace_id"], user_id=ctx["user_id"],
        platform="shopify", code="fake-code",
    )
    await service.sync_products(connection.id)
    repo = CommerceRepository(db_session)
    product = (await repo.list_products_for_connection(connection.id))[0]

    proposal = await service.generate_product_campaign_brief(
        organization_id=ctx["organization_id"], workspace_id=ctx["workspace_id"], user_id=ctx["user_id"],
        product_id=product.id, goal_slug=ctx["goal_slug"], mode="guided", target_platforms=["facebook"],
    )

    assert product.title in proposal.objective
    assert proposal.status == "draft"


async def test_abandoned_cart_content_refused_without_consent(db_session: AsyncSession) -> None:
    ctx = await _seed_workspace(db_session)
    secrets = FakeSecrets()
    adapter = FakeStoreConnector()
    service = _service(db_session, adapter=adapter, secrets=secrets)
    connection = await service.connect_store(
        organization_id=ctx["organization_id"], workspace_id=ctx["workspace_id"], user_id=ctx["user_id"],
        platform="shopify", code="fake-code",
    )
    await service.sync_products(connection.id)
    repo = CommerceRepository(db_session)
    product = (await repo.list_products_for_connection(connection.id))[0]

    with pytest.raises(ConsentRequired):
        await service.generate_abandoned_cart_content(
            organization_id=ctx["organization_id"], workspace_id=ctx["workspace_id"], user_id=ctx["user_id"],
            product_id=product.id, consent_confirmed=False,
        )


async def test_abandoned_cart_content_generated_with_consent(db_session: AsyncSession) -> None:
    ctx = await _seed_workspace(db_session)
    secrets = FakeSecrets()
    adapter = FakeStoreConnector()
    service = _service(db_session, adapter=adapter, secrets=secrets)
    connection = await service.connect_store(
        organization_id=ctx["organization_id"], workspace_id=ctx["workspace_id"], user_id=ctx["user_id"],
        platform="shopify", code="fake-code",
    )
    await service.sync_products(connection.id)
    repo = CommerceRepository(db_session)
    product = (await repo.list_products_for_connection(connection.id))[0]

    proposal = await service.generate_abandoned_cart_content(
        organization_id=ctx["organization_id"], workspace_id=ctx["workspace_id"], user_id=ctx["user_id"],
        product_id=product.id, consent_confirmed=True,
    )

    assert product.title in proposal.objective


async def _seed_two_products(db_session: AsyncSession, ctx: dict) -> tuple:
    from content_studio.ports.store_connector import ProductData, ProductPage

    secrets = FakeSecrets()
    pages = [
        ProductPage(
            products=[
                ProductData(
                    external_product_id="p1", title="Candle A", description="d1", price="10.00", currency="USD",
                    status="active", raw_payload={}, categories=["Candles"],
                    image_urls=["https://example.com/candle-a.jpg"],
                ),
                ProductData(
                    external_product_id="p2", title="Candle B", description="d2", price="20.00", currency="USD",
                    status="active", raw_payload={}, categories=["Candles", "Bestsellers"],
                ),
            ],
            next_cursor=None,
        ),
    ]
    adapter = FakeStoreConnector(pages=pages)
    service = _service(db_session, adapter=adapter, secrets=secrets)
    connection = await service.connect_store(
        organization_id=ctx["organization_id"], workspace_id=ctx["workspace_id"], user_id=ctx["user_id"],
        platform="woocommerce", code="fake-code",
    )
    await service.sync_products(connection.id)
    # build_bulk_plan_items() creates a real image plan item — needs an
    # active "image" recipe, same as _seed_workspace() seeds for "text".
    creation_repo = CreationRepository(db_session)
    await creation_repo.create_recipe(
        name=f"image-recipe-{uuid.uuid4().hex[:8]}", content_type="image", provider="replicate", model="test-model",
        estimated_cost=Decimal("2.0"),
    )
    await db_session.commit()

    repo = CommerceRepository(db_session)
    products = sorted(await repo.list_products_for_connection(connection.id), key=lambda p: p.title)
    return service, products


async def test_bulk_plan_items_creates_new_campaign_with_text_and_image_items(db_session: AsyncSession) -> None:
    ctx = await _seed_workspace(db_session)
    service, products = await _seed_two_products(db_session, ctx)

    result = await service.build_bulk_plan_items(
        organization_id=ctx["organization_id"], workspace_id=ctx["workspace_id"], user_id=ctx["user_id"],
        product_ids=[p.id for p in products], description="20% off this week", goal_slug=ctx["goal_slug"],
        target_platforms=["facebook"], campaign_id=None, generate_images=True,
    )

    assert result.failed_product_ids == []
    # Both text and image are prepared (ContentItem created) right away
    # now — dispatched in parallel, not deferred until the text is
    # approved — so both reach prepared_items for the caller
    # (bulk_generate_product_campaign) to dispatch concurrently.
    assert len(result.prepared_items) == 4  # 2 products x (text + image)
    assert {p.plan_item.content_type for p in result.prepared_items} == {"text", "image"}
    assert result.shared_image_plan_items == []  # single platform — nothing to share

    marketing_repo = MarketingRepository(db_session)
    items = await marketing_repo.list_plan_items_for_campaign(result.campaign_id)
    assert [i.sequence_number for i in items] == [1, 2, 3, 4]
    assert {i.content_type for i in items} == {"text", "image"}
    assert {i.product_id for i in items} == {p.id for p in products}

    text_item = next(i for i in items if i.product_id == products[0].id and i.content_type == "text")
    assert "Candle A" in text_item.brief_text
    assert "20% off this week" in text_item.brief_text

    # Image plan item *rows* are still "pending" with no content_item_id/
    # generation_job_id here — build_bulk_plan_items() only prepares the
    # ContentItem, it's bulk_generate_product_campaign()'s Phase A-C
    # (not exercised by this service-level test) that actually creates
    # the job and links it onto the row.
    with_reference = next(i for i in items if i.product_id == products[0].id and i.content_type == "image")
    assert with_reference.status == "pending"
    assert with_reference.content_item_id is None
    assert with_reference.generation_job_id is None
    assert with_reference.brief_text == (
        "Keep the product exactly as shown. Restyle the background to a scene that evokes "
        "'Candle A': 20% off this week"
    )

    # Candle B has no synced photo — falls back to today's text-to-image behavior.
    without_reference = next(i for i in items if i.product_id == products[1].id and i.content_type == "image")
    assert without_reference.status == "pending"
    assert without_reference.brief_text == "Candle B. 20% off this week"


async def test_bulk_plan_items_creates_a_pair_per_target_platform(db_session: AsyncSession) -> None:
    ctx = await _seed_workspace(db_session)
    service, products = await _seed_two_products(db_session, ctx)
    candle_a = products[0]

    result = await service.build_bulk_plan_items(
        organization_id=ctx["organization_id"], workspace_id=ctx["workspace_id"], user_id=ctx["user_id"],
        product_ids=[candle_a.id], description="20% off this week", goal_slug=ctx["goal_slug"],
        target_platforms=["facebook", "instagram"], campaign_id=None, generate_images=True,
    )

    assert result.failed_product_ids == []
    # One dispatched text item per platform, plus one dispatched image —
    # only the first platform's image is prepared for real; the second
    # platform's image row is recorded in shared_image_plan_items instead
    # of getting its own (necessarily-different) independent generation.
    assert len(result.prepared_items) == 3  # 2 platforms x text + 1 shared image
    assert {p.plan_item.content_type for p in result.prepared_items} == {"text", "image"}
    assert len(result.shared_image_plan_items) == 1
    shared_new_item, shared_primary_item = result.shared_image_plan_items[0]
    assert shared_new_item.target_platform == "instagram"
    assert shared_primary_item.target_platform == "facebook"

    marketing_repo = MarketingRepository(db_session)
    items = await marketing_repo.list_plan_items_for_campaign(result.campaign_id)
    assert len(items) == 4  # 1 product x 2 platforms x (text + image)

    by_platform: dict[str, dict[str, object]] = {}
    for item in items:
        by_platform.setdefault(item.target_platform, {})[item.content_type] = item
    assert set(by_platform) == {"facebook", "instagram"}
    for platform_items in by_platform.values():
        assert set(platform_items) == {"text", "image"}
        assert platform_items["text"].product_id == candle_a.id
        assert platform_items["image"].product_id == candle_a.id


async def test_bulk_generate_product_campaign_dispatches_shared_image_once_for_two_platforms(
    db_session: AsyncSession,
) -> None:
    """The real HTTP-level flow: build_bulk_plan_items() only prepares
    ContentItems; bulk_generate_product_campaign() is what actually
    creates jobs and starts workflows — this is where a shared image's
    second-platform plan item actually gets linked onto the same job the
    first platform's got, end to end, not a second independent dispatch."""
    ctx = await _seed_workspace(db_session)
    _service, products = await _seed_two_products(db_session, ctx)
    candle_a = products[0]

    context = _context(ctx)
    user = await db_session.get(User, ctx["user_id"])
    temporal = _FakeTemporalClient()

    response = await bulk_generate_product_campaign(
        body=BulkProductCampaignRequest(
            product_ids=[candle_a.id], description="20% off this week", goal_slug=ctx["goal_slug"],
            target_platforms=["facebook", "instagram"], campaign_id=None, generate_images=True,
        ),
        current_user=user, context=context, session=db_session, secrets=FakeSecrets(), temporal=temporal,
    )

    assert response.started_count == 3  # 2 text (one per platform) + 1 real image dispatch

    marketing_repo = MarketingRepository(db_session)
    items = await marketing_repo.list_plan_items_for_campaign(response.campaign_id)
    facebook_image = next(i for i in items if i.target_platform == "facebook" and i.content_type == "image")
    instagram_image = next(i for i in items if i.target_platform == "instagram" and i.content_type == "image")

    assert facebook_image.status == "generating"
    assert instagram_image.status == "generating"
    assert facebook_image.content_item_id is not None
    assert facebook_image.content_item_id == instagram_image.content_item_id
    assert facebook_image.generation_job_id == instagram_image.generation_job_id

    # Only one image workflow was actually started, not two.
    image_workflow_ids = {s["id"] for s in temporal.started if s["id"] == f"generation-{facebook_image.generation_job_id}"}
    assert len(image_workflow_ids) == 1
    assert len(temporal.started) == 3  # 2 text workflows + 1 image workflow, never 4


async def test_approving_text_dispatches_only_the_same_platform_image(db_session: AsyncSession) -> None:
    """A product with pairs for both Facebook and Instagram — approving
    Instagram's text must dispatch Instagram's image, never Facebook's,
    even though Facebook's pair was created first (lower sequence_number,
    so it'd be the first "pending" image _maybe_dispatch_paired_image()
    would find without the target_platform match added alongside this
    multi-platform support)."""
    ctx = await _seed_workspace(db_session)
    service, products = await _seed_two_products(db_session, ctx)
    candle_a = products[0]

    result = await service.build_bulk_plan_items(
        organization_id=ctx["organization_id"], workspace_id=ctx["workspace_id"], user_id=ctx["user_id"],
        product_ids=[candle_a.id], description="20% off this week", goal_slug=ctx["goal_slug"],
        target_platforms=["facebook", "instagram"], campaign_id=None, generate_images=True,
    )
    instagram_prepared = next(p for p in result.prepared_items if p.plan_item.target_platform == "instagram")

    creation_repo = CreationRepository(db_session)
    marketing_repo = MarketingRepository(db_session)
    instagram_job = await creation_repo.create_generation_job(
        organization_id=ctx["organization_id"], workspace_id=ctx["workspace_id"],
        content_item_id=instagram_prepared.prepared.content_item_id, recipe_id=instagram_prepared.prepared.recipe_id,
        requested_by_user_id=ctx["user_id"], subscription_id=ctx["subscription_id"],
        brief_text=instagram_prepared.prepared.brief_text,
    )
    await marketing_repo.link_plan_item_generation(
        instagram_prepared.plan_item, content_item_id=instagram_prepared.prepared.content_item_id,
        generation_job_id=instagram_job.id,
    )
    await creation_repo.update_job_status(instagram_job, "awaiting_review")
    await creation_repo.set_job_workflow_id(instagram_job, f"generation-{instagram_job.id}")
    await db_session.commit()

    user = await db_session.get(User, ctx["user_id"])
    temporal = _FakeTemporalClient()
    await review_generation_job(
        job_id=instagram_job.id, body=ReviewRequest(decision="approved", revision_id=uuid.uuid4(), comment=None),
        current_user=user, context=_context(ctx), session=db_session, temporal=temporal,
    )

    items_after = await marketing_repo.list_plan_items_for_campaign(result.campaign_id)
    facebook_image = next(i for i in items_after if i.target_platform == "facebook" and i.content_type == "image")
    instagram_image = next(i for i in items_after if i.target_platform == "instagram" and i.content_type == "image")

    assert instagram_image.status == "generating"
    assert instagram_image.generation_job_id is not None
    assert facebook_image.status == "pending"
    assert facebook_image.generation_job_id is None
    assert len(temporal.started) == 1


async def test_approving_second_platform_text_reuses_first_platforms_generated_image(
    db_session: AsyncSession,
) -> None:
    """Facebook and Instagram share one underlying generated image for the
    same product — once Facebook's image has actually generated, approving
    Instagram's text must link its image item to that same
    content_item_id/generation_job_id instead of dispatching a second,
    necessarily-different independent AI image generation."""
    ctx = await _seed_workspace(db_session)
    service, products = await _seed_two_products(db_session, ctx)
    candle_a = products[0]

    result = await service.build_bulk_plan_items(
        organization_id=ctx["organization_id"], workspace_id=ctx["workspace_id"], user_id=ctx["user_id"],
        product_ids=[candle_a.id], description="20% off this week", goal_slug=ctx["goal_slug"],
        target_platforms=["facebook", "instagram"], campaign_id=None, generate_images=True,
    )
    facebook_prepared = next(p for p in result.prepared_items if p.plan_item.target_platform == "facebook")
    instagram_prepared = next(p for p in result.prepared_items if p.plan_item.target_platform == "instagram")

    creation_repo = CreationRepository(db_session)
    marketing_repo = MarketingRepository(db_session)
    user = await db_session.get(User, ctx["user_id"])

    async def _approve_text(prepared) -> None:
        job = await creation_repo.create_generation_job(
            organization_id=ctx["organization_id"], workspace_id=ctx["workspace_id"],
            content_item_id=prepared.prepared.content_item_id, recipe_id=prepared.prepared.recipe_id,
            requested_by_user_id=ctx["user_id"], subscription_id=ctx["subscription_id"],
            brief_text=prepared.prepared.brief_text,
        )
        await marketing_repo.link_plan_item_generation(
            prepared.plan_item, content_item_id=prepared.prepared.content_item_id, generation_job_id=job.id
        )
        await creation_repo.update_job_status(job, "awaiting_review")
        await creation_repo.set_job_workflow_id(job, f"generation-{job.id}")
        await db_session.commit()
        await review_generation_job(
            job_id=job.id, body=ReviewRequest(decision="approved", revision_id=uuid.uuid4(), comment=None),
            current_user=user, context=_context(ctx), session=db_session, temporal=_FakeTemporalClient(),
        )

    await _approve_text(facebook_prepared)

    items_after_fb = await marketing_repo.list_plan_items_for_campaign(result.campaign_id)
    facebook_image = next(i for i in items_after_fb if i.target_platform == "facebook" and i.content_type == "image")
    instagram_image_before = next(
        i for i in items_after_fb if i.target_platform == "instagram" and i.content_type == "image"
    )
    assert facebook_image.status == "generating"
    assert facebook_image.content_item_id is not None
    assert instagram_image_before.status == "pending"
    assert instagram_image_before.content_item_id is None

    await _approve_text(instagram_prepared)

    items_after_ig = await marketing_repo.list_plan_items_for_campaign(result.campaign_id)
    facebook_image_after = next(
        i for i in items_after_ig if i.target_platform == "facebook" and i.content_type == "image"
    )
    instagram_image_after = next(
        i for i in items_after_ig if i.target_platform == "instagram" and i.content_type == "image"
    )

    assert instagram_image_after.status == "generating"
    assert instagram_image_after.content_item_id == facebook_image_after.content_item_id
    assert instagram_image_after.generation_job_id == facebook_image_after.generation_job_id


async def test_rejecting_shared_image_recreates_it_for_every_platform_sharing_it(
    db_session: AsyncSession,
) -> None:
    """Facebook and Instagram share one generated image for the same
    product. Rejecting it on Facebook must recreate it for Instagram too —
    not leave Instagram's item stuck pointing at the rejected job — since
    the user only ever sees/rejects it once (via whichever platform's
    review panel they happened to open)."""
    ctx = await _seed_workspace(db_session)
    service, products = await _seed_two_products(db_session, ctx)
    candle_a = products[0]

    result = await service.build_bulk_plan_items(
        organization_id=ctx["organization_id"], workspace_id=ctx["workspace_id"], user_id=ctx["user_id"],
        product_ids=[candle_a.id], description="20% off this week", goal_slug=ctx["goal_slug"],
        target_platforms=["facebook", "instagram"], campaign_id=None, generate_images=True,
    )
    facebook_prepared = next(p for p in result.prepared_items if p.plan_item.target_platform == "facebook")
    instagram_prepared = next(p for p in result.prepared_items if p.plan_item.target_platform == "instagram")

    creation_repo = CreationRepository(db_session)
    marketing_repo = MarketingRepository(db_session)
    user = await db_session.get(User, ctx["user_id"])

    async def _approve_text(prepared) -> None:
        job = await creation_repo.create_generation_job(
            organization_id=ctx["organization_id"], workspace_id=ctx["workspace_id"],
            content_item_id=prepared.prepared.content_item_id, recipe_id=prepared.prepared.recipe_id,
            requested_by_user_id=ctx["user_id"], subscription_id=ctx["subscription_id"],
            brief_text=prepared.prepared.brief_text,
        )
        await marketing_repo.link_plan_item_generation(
            prepared.plan_item, content_item_id=prepared.prepared.content_item_id, generation_job_id=job.id
        )
        await creation_repo.update_job_status(job, "awaiting_review")
        await creation_repo.set_job_workflow_id(job, f"generation-{job.id}")
        await db_session.commit()
        await review_generation_job(
            job_id=job.id, body=ReviewRequest(decision="approved", revision_id=uuid.uuid4(), comment=None),
            current_user=user, context=_context(ctx), session=db_session, temporal=_FakeTemporalClient(),
        )

    await _approve_text(facebook_prepared)
    await _approve_text(instagram_prepared)

    items = await marketing_repo.list_plan_items_for_campaign(result.campaign_id)
    facebook_image = next(i for i in items if i.target_platform == "facebook" and i.content_type == "image")
    instagram_image = next(i for i in items if i.target_platform == "instagram" and i.content_type == "image")
    shared_job_id = facebook_image.generation_job_id
    assert instagram_image.generation_job_id == shared_job_id  # sanity check on the setup

    # Mark the shared job awaiting review (as if it had actually finished
    # generating), then reject it via Facebook's plan item.
    await creation_repo.update_job_status(
        await creation_repo.get_generation_job_by_id(shared_job_id), "awaiting_review"
    )
    await creation_repo.set_job_workflow_id(
        await creation_repo.get_generation_job_by_id(shared_job_id), f"generation-{shared_job_id}"
    )
    await db_session.commit()

    result_reject = await review_generation_job(
        job_id=shared_job_id, body=ReviewRequest(decision="rejected", revision_id=uuid.uuid4(), comment="try again"),
        current_user=user, context=_context(ctx), session=db_session, temporal=_FakeTemporalClient(),
    )
    new_job_id = result_reject["new_job_id"]
    assert new_job_id is not None
    assert new_job_id != str(shared_job_id)

    refreshed = await marketing_repo.list_plan_items_for_campaign(result.campaign_id)
    refreshed_facebook = next(i for i in refreshed if i.target_platform == "facebook" and i.content_type == "image")
    refreshed_instagram = next(i for i in refreshed if i.target_platform == "instagram" and i.content_type == "image")

    assert str(refreshed_facebook.generation_job_id) == new_job_id
    assert str(refreshed_instagram.generation_job_id) == new_job_id
    assert refreshed_facebook.content_item_id == refreshed_instagram.content_item_id


async def test_bulk_plan_items_appends_to_existing_campaign_without_images(db_session: AsyncSession) -> None:
    ctx = await _seed_workspace(db_session)
    service, products = await _seed_two_products(db_session, ctx)

    first = await service.build_bulk_plan_items(
        organization_id=ctx["organization_id"], workspace_id=ctx["workspace_id"], user_id=ctx["user_id"],
        product_ids=[products[0].id], description="launch week", goal_slug=ctx["goal_slug"],
        target_platforms=[], campaign_id=None, generate_images=False,
    )
    assert len(first.prepared_items) == 1  # text only

    second = await service.build_bulk_plan_items(
        organization_id=ctx["organization_id"], workspace_id=ctx["workspace_id"], user_id=ctx["user_id"],
        product_ids=[products[1].id], description="still launch week", goal_slug=ctx["goal_slug"],
        target_platforms=[], campaign_id=first.campaign_id, generate_images=False,
    )

    assert second.campaign_id == first.campaign_id
    marketing_repo = MarketingRepository(db_session)
    items = await marketing_repo.list_plan_items_for_campaign(first.campaign_id)
    assert [i.sequence_number for i in items] == [1, 2]
    assert all(i.content_type == "text" for i in items)


async def test_bulk_plan_items_collects_failed_product_ids(db_session: AsyncSession) -> None:
    ctx = await _seed_workspace(db_session)
    service, products = await _seed_two_products(db_session, ctx)
    missing_id = uuid.uuid4()

    result = await service.build_bulk_plan_items(
        organization_id=ctx["organization_id"], workspace_id=ctx["workspace_id"], user_id=ctx["user_id"],
        product_ids=[products[0].id, missing_id], description="promo", goal_slug=ctx["goal_slug"],
        target_platforms=[], campaign_id=None, generate_images=False,
    )

    assert result.failed_product_ids == [missing_id]
    assert len(result.prepared_items) == 1


async def test_bulk_plan_items_raises_for_unknown_campaign(db_session: AsyncSession) -> None:
    ctx = await _seed_workspace(db_session)
    service, products = await _seed_two_products(db_session, ctx)

    with pytest.raises(CampaignNotFound):
        await service.build_bulk_plan_items(
            organization_id=ctx["organization_id"], workspace_id=ctx["workspace_id"], user_id=ctx["user_id"],
            product_ids=[products[0].id], description="promo", goal_slug=ctx["goal_slug"],
            target_platforms=[], campaign_id=uuid.uuid4(), generate_images=False,
        )


async def test_bulk_plan_items_briefs_include_brand_context_and_style_reference(db_session: AsyncSession) -> None:
    ctx = await _seed_workspace(db_session)
    service, products = await _seed_two_products(db_session, ctx)

    identity_repo = IdentityRepository(db_session)
    await identity_repo.create_brand_profile(
        workspace_id=ctx["workspace_id"], name="Default", tone_description=None,
        product_line_description="Soy scented candles, room diffusers, car diffusers, plant-based wax melts",
        brand_pillars_description="Sell the experience, not the product.",
        vocabulary=[], colors=[], target_audiences=[], default_ctas=[],
    )

    publishing_repo = PublishingRepository(db_session)
    # Seal through the same FakeSecrets instance build_bulk_plan_items()
    # will later unseal from (service._secrets, set by _seed_two_products()).
    token_ref = await service._secrets.seal(value="fake-page-token")
    await publishing_repo.create_connection(
        organization_id=ctx["organization_id"], workspace_id=ctx["workspace_id"],
        connected_by_user_id=ctx["user_id"], platform="facebook", external_account_id="fake-page-1",
        external_account_name="Fake Page", access_token_secret_ref=token_ref, refresh_token_secret_ref=None,
        scopes=[],
    )
    await db_session.commit()

    result = await service.build_bulk_plan_items(
        organization_id=ctx["organization_id"], workspace_id=ctx["workspace_id"], user_id=ctx["user_id"],
        product_ids=[products[0].id], description="20% off this week", goal_slug=ctx["goal_slug"],
        target_platforms=[], campaign_id=None, generate_images=True,
    )

    marketing_repo = MarketingRepository(db_session)
    items = await marketing_repo.list_plan_items_for_campaign(result.campaign_id)
    text_item = next(i for i in items if i.content_type == "text")
    image_item = next(i for i in items if i.content_type == "image")

    assert "Soy scented candles" in text_item.brief_text
    assert "20% off this week" in text_item.brief_text
    assert "Sell the experience, not the product." in text_item.brief_text
    # StubSocialPlatformAdapter.list_recent_posts() is what get_social_platform_adapter()
    # falls back to with no real Meta app configured (the case in tests) — its
    # canned captions prove the whole lookup->unseal->adapter->extract chain works.
    assert "New arrivals just dropped" in text_item.brief_text
    # Candle A has a synced photo — image brief is the edit-style prompt, not a re-description.
    assert "20% off this week" in image_item.brief_text
    assert "Sell the experience" not in image_item.brief_text
    assert image_item.brief_text == (
        "Keep the product exactly as shown. Restyle the background to a scene that evokes "
        "'Candle A': 20% off this week"
    )


async def test_bulk_plan_items_text_briefs_include_rejection_feedback_but_image_briefs_dont(
    db_session: AsyncSession,
) -> None:
    ctx = await _seed_workspace(db_session)
    service, products = await _seed_two_products(db_session, ctx)

    creation_repo = CreationRepository(db_session)
    item = await creation_repo.create_content_item(
        organization_id=ctx["organization_id"], workspace_id=ctx["workspace_id"],
        created_by_user_id=ctx["user_id"], content_type="text", title="Past attempt",
    )
    revision = await creation_repo.create_revision(
        content_item_id=item.id, generation_attempt_id=None, revision_number=1, text_body="Old draft",
    )
    await creation_repo.create_review(
        content_revision_id=revision.id, reviewer_user_id=ctx["user_id"], decision="rejected",
        comment="Avoid using emojis in captions",
    )
    await db_session.commit()

    result = await service.build_bulk_plan_items(
        organization_id=ctx["organization_id"], workspace_id=ctx["workspace_id"], user_id=ctx["user_id"],
        product_ids=[products[0].id], description="20% off this week", goal_slug=ctx["goal_slug"],
        target_platforms=[], campaign_id=None, generate_images=True,
    )

    marketing_repo = MarketingRepository(db_session)
    items = await marketing_repo.list_plan_items_for_campaign(result.campaign_id)
    text_item = next(i for i in items if i.content_type == "text")
    image_item = next(i for i in items if i.content_type == "image")

    assert "Avoid these previously flagged issues:" in text_item.brief_text
    assert "Avoid using emojis in captions" in text_item.brief_text
    assert "Avoid using emojis in captions" not in image_item.brief_text


async def test_bulk_plan_items_text_briefs_include_learned_deletions(db_session: AsyncSession) -> None:
    ctx = await _seed_workspace(db_session)
    service, products = await _seed_two_products(db_session, ctx)

    creation_repo = CreationRepository(db_session)
    item = await creation_repo.create_content_item(
        organization_id=ctx["organization_id"], workspace_id=ctx["workspace_id"],
        created_by_user_id=ctx["user_id"], content_type="text", title="Past attempt",
    )
    revision = await creation_repo.create_revision(
        content_item_id=item.id, generation_attempt_id=None, revision_number=1, text_body="Old draft",
    )
    await creation_repo.create_text_edit_learning(
        organization_id=ctx["organization_id"], workspace_id=ctx["workspace_id"],
        source_content_revision_id=revision.id, deleted_text="handmade with love in Greece",
    )
    await db_session.commit()

    result = await service.build_bulk_plan_items(
        organization_id=ctx["organization_id"], workspace_id=ctx["workspace_id"], user_id=ctx["user_id"],
        product_ids=[products[0].id], description="20% off this week", goal_slug=ctx["goal_slug"],
        target_platforms=[], campaign_id=None, generate_images=True,
    )

    marketing_repo = MarketingRepository(db_session)
    items = await marketing_repo.list_plan_items_for_campaign(result.campaign_id)
    text_item = next(i for i in items if i.content_type == "text")
    image_item = next(i for i in items if i.content_type == "image")

    assert "Don't include phrases like these" in text_item.brief_text
    assert "handmade with love in Greece" in text_item.brief_text
    assert "handmade with love in Greece" not in image_item.brief_text


async def _dispatch_text_item_to_awaiting_review(db_session: AsyncSession, ctx: dict, result) -> object:
    """Mirrors what commerce.py's bulk-campaign API endpoint (Phase A-C)
    does for the text item — build_bulk_plan_items() itself only creates
    the ContentItem, not the GenerationJob/dispatch, since starting
    workflows needs to happen outside the service layer."""
    creation_repo = CreationRepository(db_session)
    marketing_repo = MarketingRepository(db_session)
    text_prepared = result.prepared_items[0]
    text_job = await creation_repo.create_generation_job(
        organization_id=ctx["organization_id"], workspace_id=ctx["workspace_id"],
        content_item_id=text_prepared.prepared.content_item_id, recipe_id=text_prepared.prepared.recipe_id,
        requested_by_user_id=ctx["user_id"], subscription_id=ctx["subscription_id"],
        brief_text=text_prepared.prepared.brief_text,
    )
    await marketing_repo.link_plan_item_generation(
        text_prepared.plan_item, content_item_id=text_prepared.prepared.content_item_id, generation_job_id=text_job.id
    )
    await creation_repo.update_job_status(text_job, "awaiting_review")
    await creation_repo.set_job_workflow_id(text_job, f"generation-{text_job.id}")
    await db_session.commit()
    return text_job


def _context(ctx: dict) -> WorkspaceContext:
    return WorkspaceContext(
        organization_id=ctx["organization_id"], workspace_id=ctx["workspace_id"],
        subscription_id=ctx["subscription_id"], role_permissions=[],
    )


async def test_approving_text_dispatches_paired_pending_image_with_current_photo(db_session: AsyncSession) -> None:
    ctx = await _seed_workspace(db_session)
    service, products = await _seed_two_products(db_session, ctx)
    candle_a = products[0]  # has a synced photo, see _seed_two_products

    result = await service.build_bulk_plan_items(
        organization_id=ctx["organization_id"], workspace_id=ctx["workspace_id"], user_id=ctx["user_id"],
        product_ids=[candle_a.id], description="20% off this week", goal_slug=ctx["goal_slug"],
        target_platforms=[], campaign_id=None, generate_images=True,
    )
    text_job = await _dispatch_text_item_to_awaiting_review(db_session, ctx, result)

    marketing_repo = MarketingRepository(db_session)
    items_before = await marketing_repo.list_plan_items_for_campaign(result.campaign_id)
    image_item_before = next(i for i in items_before if i.content_type == "image")
    assert image_item_before.status == "pending"
    assert image_item_before.generation_job_id is None

    user = await db_session.get(User, ctx["user_id"])
    temporal = _FakeTemporalClient()
    await review_generation_job(
        job_id=text_job.id, body=ReviewRequest(decision="approved", revision_id=uuid.uuid4(), comment=None),
        current_user=user, context=_context(ctx), session=db_session, temporal=temporal,
    )

    creation_repo = CreationRepository(db_session)
    items_after = await marketing_repo.list_plan_items_for_campaign(result.campaign_id)
    image_item_after = next(i for i in items_after if i.content_type == "image")
    assert image_item_after.status == "generating"
    assert image_item_after.generation_job_id is not None

    image_job = await creation_repo.get_generation_job_by_id(image_item_after.generation_job_id)
    assert image_job.reference_image_url == "https://example.com/candle-a.jpg"
    assert len(temporal.started) == 1


async def test_approving_text_uses_product_photo_synced_after_campaign_created(db_session: AsyncSession) -> None:
    ctx = await _seed_workspace(db_session)
    service, products = await _seed_two_products(db_session, ctx)
    candle_b = products[1]  # no synced photo at seed time, see _seed_two_products

    result = await service.build_bulk_plan_items(
        organization_id=ctx["organization_id"], workspace_id=ctx["workspace_id"], user_id=ctx["user_id"],
        product_ids=[candle_b.id], description="20% off this week", goal_slug=ctx["goal_slug"],
        target_platforms=[], campaign_id=None, generate_images=True,
    )

    # A photo gets synced for this product *after* the campaign was already
    # built — the exact scenario this whole change exists to fix.
    commerce_repo = CommerceRepository(db_session)
    await commerce_repo.upsert_asset(
        product_id=candle_b.id, external_asset_id="candle-b-image-0",
        url="https://example.com/candle-b-new.jpg", position=0,
    )
    await db_session.commit()

    text_job = await _dispatch_text_item_to_awaiting_review(db_session, ctx, result)

    user = await db_session.get(User, ctx["user_id"])
    temporal = _FakeTemporalClient()
    await review_generation_job(
        job_id=text_job.id, body=ReviewRequest(decision="approved", revision_id=uuid.uuid4(), comment=None),
        current_user=user, context=_context(ctx), session=db_session, temporal=temporal,
    )

    marketing_repo = MarketingRepository(db_session)
    creation_repo = CreationRepository(db_session)
    items_after = await marketing_repo.list_plan_items_for_campaign(result.campaign_id)
    image_item_after = next(i for i in items_after if i.content_type == "image")
    image_job = await creation_repo.get_generation_job_by_id(image_item_after.generation_job_id)

    assert image_job.reference_image_url == "https://example.com/candle-b-new.jpg"
    # The final brief reflects the edit-style prompt now that a photo
    # exists, not the plain text-to-image prompt stored as a preview when
    # the campaign was first built (no photo yet at that point).
    assert image_job.brief_text.startswith("Keep the product exactly as shown.")
    assert image_item_after.brief_text == image_job.brief_text


async def test_manual_start_blocks_image_until_text_approved_then_uses_fresh_photo(db_session: AsyncSession) -> None:
    from fastapi import HTTPException

    from content_studio.api.v1.marketing import start_plan_item

    ctx = await _seed_workspace(db_session)
    service, products = await _seed_two_products(db_session, ctx)
    candle_a = products[0]

    result = await service.build_bulk_plan_items(
        organization_id=ctx["organization_id"], workspace_id=ctx["workspace_id"], user_id=ctx["user_id"],
        product_ids=[candle_a.id], description="20% off this week", goal_slug=ctx["goal_slug"],
        target_platforms=[], campaign_id=None, generate_images=True,
    )
    marketing_repo = MarketingRepository(db_session)
    items = await marketing_repo.list_plan_items_for_campaign(result.campaign_id)
    image_item = next(i for i in items if i.content_type == "image")

    user = await db_session.get(User, ctx["user_id"])
    temporal = _FakeTemporalClient()

    with pytest.raises(HTTPException) as exc_info:
        await start_plan_item(
            campaign_id=result.campaign_id, item_id=image_item.id, current_user=user, context=_context(ctx),
            session=db_session, temporal=temporal,
        )
    assert exc_info.value.status_code == 409

    creation_repo = CreationRepository(db_session)
    text_prepared = result.prepared_items[0]
    text_job = await creation_repo.create_generation_job(
        organization_id=ctx["organization_id"], workspace_id=ctx["workspace_id"],
        content_item_id=text_prepared.prepared.content_item_id, recipe_id=text_prepared.prepared.recipe_id,
        requested_by_user_id=ctx["user_id"], subscription_id=ctx["subscription_id"],
        brief_text=text_prepared.prepared.brief_text,
    )
    await marketing_repo.link_plan_item_generation(
        text_prepared.plan_item, content_item_id=text_prepared.prepared.content_item_id, generation_job_id=text_job.id
    )
    await creation_repo.update_job_status(text_job, "approved")
    await db_session.commit()

    result_start = await start_plan_item(
        campaign_id=result.campaign_id, item_id=image_item.id, current_user=user, context=_context(ctx),
        session=db_session, temporal=temporal,
    )
    assert result_start["status"] == "started"

    refreshed_image_item = await marketing_repo.get_plan_item_by_id(image_item.id)
    image_job = await creation_repo.get_generation_job_by_id(refreshed_image_item.generation_job_id)
    assert image_job.reference_image_url == "https://example.com/candle-a.jpg"


async def test_strip_product_size_removes_weight_suffix() -> None:
    assert _strip_product_size('Mistral "Artwood Collection" Χειροποίητο Κερί Σόγιας 200γρ.') == (
        'Mistral "Artwood Collection" Χειροποίητο Κερί Σόγιας'
    )
    assert _strip_product_size("BAMBOO | Wax Melts Κύβοι 70γρ") == "BAMBOO | Wax Melts Κύβοι"
    assert _strip_product_size("Whiskey Caramel Κερί Σόγιας 60γρ") == "Whiskey Caramel Κερί Σόγιας"
    # No weight suffix present — left unchanged.
    assert _strip_product_size("WOODLAND | Wax Melts Κύβοι") == "WOODLAND | Wax Melts Κύβοι"


async def test_bulk_plan_items_briefs_strip_product_weight_suffix(db_session: AsyncSession) -> None:
    from content_studio.ports.store_connector import ProductData, ProductPage

    ctx = await _seed_workspace(db_session)
    secrets = FakeSecrets()
    pages = [
        ProductPage(
            products=[
                ProductData(
                    external_product_id="p1", title="Mistral Χειροποίητο Κερί Σόγιας 200γρ.", description="d1",
                    price="10.00", currency="USD", status="active", raw_payload={},
                    image_urls=["https://example.com/mistral.jpg"],
                ),
            ],
            next_cursor=None,
        ),
    ]
    adapter = FakeStoreConnector(pages=pages)
    service = _service(db_session, adapter=adapter, secrets=secrets)
    connection = await service.connect_store(
        organization_id=ctx["organization_id"], workspace_id=ctx["workspace_id"], user_id=ctx["user_id"],
        platform="woocommerce", code="fake-code",
    )
    await service.sync_products(connection.id)
    creation_repo = CreationRepository(db_session)
    await creation_repo.create_recipe(
        name=f"image-recipe-{uuid.uuid4().hex[:8]}", content_type="image", provider="replicate", model="test-model",
        estimated_cost=Decimal("2.0"),
    )
    await db_session.commit()

    repo = CommerceRepository(db_session)
    product = (await repo.list_products_for_connection(connection.id))[0]

    result = await service.build_bulk_plan_items(
        organization_id=ctx["organization_id"], workspace_id=ctx["workspace_id"], user_id=ctx["user_id"],
        product_ids=[product.id], description="new arrivals", goal_slug=ctx["goal_slug"],
        target_platforms=[], campaign_id=None, generate_images=True,
    )

    marketing_repo = MarketingRepository(db_session)
    items = await marketing_repo.list_plan_items_for_campaign(result.campaign_id)
    text_item = next(i for i in items if i.content_type == "text")
    image_item = next(i for i in items if i.content_type == "image")

    assert "200γρ" not in text_item.brief_text
    assert "200γρ" not in image_item.brief_text
    assert "Mistral" in text_item.brief_text


async def test_editing_revision_text_propagates_deletion_to_pending_siblings_only(db_session: AsyncSession) -> None:
    ctx = await _seed_workspace(db_session)
    service, products = await _seed_two_products(db_session, ctx)

    result = await service.build_bulk_plan_items(
        organization_id=ctx["organization_id"], workspace_id=ctx["workspace_id"], user_id=ctx["user_id"],
        product_ids=[p.id for p in products], description="20% off this week", goal_slug=ctx["goal_slug"],
        target_platforms=[], campaign_id=None, generate_images=False,
    )
    assert len(result.prepared_items) == 2

    creation_repo = CreationRepository(db_session)
    marketing_repo = MarketingRepository(db_session)

    shared_phrase = "handmade with love in Greece"
    revisions = []
    for prepared_item in result.prepared_items:
        job = await creation_repo.create_generation_job(
            organization_id=ctx["organization_id"], workspace_id=ctx["workspace_id"],
            content_item_id=prepared_item.prepared.content_item_id, recipe_id=prepared_item.prepared.recipe_id,
            requested_by_user_id=ctx["user_id"], subscription_id=ctx["subscription_id"],
            brief_text=prepared_item.prepared.brief_text,
        )
        await marketing_repo.link_plan_item_generation(
            prepared_item.plan_item, content_item_id=prepared_item.prepared.content_item_id, generation_job_id=job.id
        )
        await creation_repo.update_job_status(job, "awaiting_review")
        revision = await creation_repo.create_revision(
            content_item_id=prepared_item.prepared.content_item_id, generation_attempt_id=None, revision_number=1,
            text_body=f"Check out this candle — {shared_phrase}. Only this week!",
        )
        revisions.append(revision)
    await db_session.commit()

    # A third item, already approved — must be left untouched even though
    # its text also contains the phrase being deleted.
    third_item = await creation_repo.create_content_item(
        organization_id=ctx["organization_id"], workspace_id=ctx["workspace_id"], created_by_user_id=ctx["user_id"],
        content_type="text", title="Already decided",
    )
    third_revision = await creation_repo.create_revision(
        content_item_id=third_item.id, generation_attempt_id=None, revision_number=1,
        text_body=f"Another caption, {shared_phrase}, already approved.",
    )
    third_plan_item = await marketing_repo.create_plan_item(
        campaign_id=result.campaign_id, sequence_number=99, title="Already decided",
        brief_text="n/a", product_id=products[0].id, content_type="text",
    )
    third_job = await creation_repo.create_generation_job(
        organization_id=ctx["organization_id"], workspace_id=ctx["workspace_id"], content_item_id=third_item.id,
        recipe_id=result.prepared_items[0].prepared.recipe_id, requested_by_user_id=ctx["user_id"],
        subscription_id=ctx["subscription_id"], brief_text="n/a",
    )
    await marketing_repo.link_plan_item_generation(
        third_plan_item, content_item_id=third_item.id, generation_job_id=third_job.id
    )
    await creation_repo.update_job_status(third_job, "approved")
    await db_session.commit()

    context = _context(ctx)
    user = await db_session.get(User, ctx["user_id"])
    edited_text = "Check out this candle. Only this week!"
    response = await edit_revision_text(
        revision_id=revisions[0].id, body=EditRevisionTextRequest(text_body=edited_text),
        current_user=user, context=context, session=db_session,
    )

    assert response.applied_to_siblings == 1
    assert response.revision.text_body == edited_text

    refreshed_sibling = await creation_repo.get_revision_by_id(revisions[1].id)
    assert shared_phrase not in refreshed_sibling.text_body

    refreshed_third = await creation_repo.get_revision_by_id(third_revision.id)
    assert shared_phrase in refreshed_third.text_body  # already-decided item left alone

    learnings = await creation_repo.list_recent_text_edit_learnings_for_workspace(ctx["workspace_id"])
    assert any(shared_phrase in learning for learning in learnings)
