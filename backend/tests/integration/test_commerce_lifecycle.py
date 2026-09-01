import json
import uuid
from decimal import Decimal

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from content_studio.modules.billing.repository import BillingRepository
from content_studio.modules.billing.service import LedgerService
from content_studio.modules.commerce.exceptions import ConsentRequired
from content_studio.modules.commerce.repository import CommerceRepository
from content_studio.modules.commerce.service import CommerceService
from content_studio.modules.commerce.webhook_signature import compute_signature
from content_studio.modules.creation.repository import CreationRepository
from content_studio.modules.identity.repository import IdentityRepository
from content_studio.modules.identity.service import IdentityService
from content_studio.modules.marketing.exceptions import CampaignNotFound
from content_studio.modules.marketing.repository import MarketingRepository
from content_studio.modules.publishing.repository import PublishingRepository
from tests.fakes.secrets import FakeSecrets
from tests.fakes.store_connector import FakeStoreConnector

pytestmark = pytest.mark.asyncio


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
    assert len(result.prepared_items) == 4  # 2 products x (text + image)

    marketing_repo = MarketingRepository(db_session)
    items = await marketing_repo.list_plan_items_for_campaign(result.campaign_id)
    assert [i.sequence_number for i in items] == [1, 2, 3, 4]
    assert {i.content_type for i in items} == {"text", "image"}
    assert {i.product_id for i in items} == {p.id for p in products}

    text_item = next(i for i in items if i.product_id == products[0].id and i.content_type == "text")
    assert "Candle A" in text_item.brief_text
    assert "20% off this week" in text_item.brief_text

    # Candle A has a synced photo (see _seed_two_products) — its image item
    # should get an edit-style prompt and carry the reference URL forward,
    # not re-describe the product from scratch.
    with_reference = next(p for p in result.prepared_items if p.plan_item.product_id == products[0].id and p.plan_item.content_type == "image")
    assert with_reference.prepared.reference_image_url == "https://example.com/candle-a.jpg"
    assert with_reference.plan_item.brief_text == (
        "Keep the product exactly as shown. Restyle the background to a scene that evokes "
        "'Candle A': 20% off this week"
    )

    # Candle B has no synced photo — falls back to today's text-to-image behavior.
    without_reference = next(p for p in result.prepared_items if p.plan_item.product_id == products[1].id and p.plan_item.content_type == "image")
    assert without_reference.prepared.reference_image_url is None
    assert without_reference.plan_item.brief_text == "Candle B. 20% off this week"


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
    # StubSocialPlatformAdapter.list_recent_posts() is what get_social_platform_adapter()
    # falls back to with no real Meta app configured (the case in tests) — its
    # canned captions prove the whole lookup->unseal->adapter->extract chain works.
    assert "New arrivals just dropped" in text_item.brief_text
    # Candle A has a synced photo — image brief is the edit-style prompt, not a re-description.
    assert "20% off this week" in image_item.brief_text
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
