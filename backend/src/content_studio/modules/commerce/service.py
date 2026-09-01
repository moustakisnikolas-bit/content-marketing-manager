import json
import re
import uuid
from collections.abc import Callable
from dataclasses import dataclass, replace
from decimal import Decimal

import httpx
from sqlalchemy.ext.asyncio import AsyncSession

from content_studio.adapters.factory import get_social_platform_adapter
from content_studio.config import get_settings
from content_studio.modules.commerce.exceptions import (
    ConsentRequired,
    ProductNotFound,
    StoreNotFound,
)
from content_studio.modules.commerce.models import Product, StoreConnection
from content_studio.modules.commerce.repository import CommerceRepository
from content_studio.modules.commerce.webhook_signature import verify_signature
from content_studio.modules.creation.repository import CreationRepository
from content_studio.modules.governance.service import AuditService
from content_studio.modules.identity.repository import IdentityRepository
from content_studio.modules.marketing.exceptions import CampaignNotFound, NoActiveRecipe
from content_studio.modules.marketing.models import Campaign, CampaignPlanItem, CampaignProposal
from content_studio.modules.marketing.repository import MarketingRepository
from content_studio.modules.marketing.service import MarketingService, PreparedGeneration
from content_studio.modules.publishing.repository import PublishingRepository
from content_studio.ports.secrets import SecretsPort
from content_studio.ports.store_connector import StoreConnectorPort

ABANDONED_CART_GOAL_SLUG = "retargeting"


@dataclass(frozen=True)
class SyncResult:
    products_synced: int
    next_cursor: str | None


@dataclass(frozen=True)
class BulkPlanItemPrepared:
    plan_item: CampaignPlanItem
    prepared: PreparedGeneration


@dataclass(frozen=True)
class BulkCampaignResult:
    campaign_id: uuid.UUID
    prepared_items: list[BulkPlanItemPrepared]
    failed_product_ids: list[uuid.UUID]


@dataclass(frozen=True)
class WebhookResult:
    accepted: bool
    delivery_id: str


class CommerceService:
    """Called both from the API (connect/list/sync) and from the
    unauthenticated webhook receiver. Store adapters are resolved per-call
    from a connection's actual platform via store_adapter_factory, same
    pattern MetricsIngestionService uses in the analytics module —
    necessary since a single service instance may handle connections to
    different platforms across calls."""

    def __init__(
        self,
        session: AsyncSession,
        *,
        secrets: SecretsPort,
        store_adapter_factory: Callable[[str], StoreConnectorPort],
    ) -> None:
        self._session = session
        self._repo = CommerceRepository(session)
        self._secrets = secrets
        self._store_adapter_factory = store_adapter_factory
        self._audit = AuditService(session)

    async def connect_store(
        self,
        *,
        organization_id: uuid.UUID,
        workspace_id: uuid.UUID,
        user_id: uuid.UUID,
        platform: str,
        code: str,
    ) -> StoreConnection:
        adapter = self._store_adapter_factory(platform)
        token = await adapter.exchange_code_for_token(code=code)

        access_ref = await self._secrets.seal(value=token.access_token)
        webhook_ref = await self._secrets.seal(value=token.webhook_secret)

        connection = await self._repo.create_connection(
            organization_id=organization_id,
            workspace_id=workspace_id,
            connected_by_user_id=user_id,
            platform=platform,
            store_domain=token.store_domain,
            external_store_id=token.external_store_id,
            access_token_secret_ref=access_ref,
            webhook_secret_ref=webhook_ref,
            scopes=token.scopes,
        )
        await self.refresh_capabilities(connection.id)

        await self._audit.record(
            event_type="commerce.store_connected",
            actor_type="user",
            actor_id=str(user_id),
            organization_id=organization_id,
            summary=f"Connected {platform} store '{token.external_account_name}'",
            payload={"connection_id": str(connection.id), "platform": platform},
        )
        await self._session.commit()
        return connection

    async def connect_store_with_credentials(
        self,
        *,
        organization_id: uuid.UUID,
        workspace_id: uuid.UUID,
        user_id: uuid.UUID,
        platform: str,
        store_domain: str,
        consumer_key: str,
        consumer_secret: str,
    ) -> StoreConnection:
        """Connect path for platforms with no OAuth2 redirect (WooCommerce)
        — see connect_with_credentials()'s docstring on StoreConnectorPort.
        Webhook registration happens after the connection row exists
        (delivery_url embeds its id), unlike connect_store()'s single-shot
        flow — that's the one real structural difference from the OAuth
        path."""
        adapter = self._store_adapter_factory(platform)
        token = await adapter.connect_with_credentials(
            store_domain=store_domain, consumer_key=consumer_key, consumer_secret=consumer_secret
        )

        access_ref = await self._secrets.seal(value=token.access_token)
        webhook_ref = await self._secrets.seal(value=token.webhook_secret)

        connection = await self._repo.create_connection(
            organization_id=organization_id,
            workspace_id=workspace_id,
            connected_by_user_id=user_id,
            platform=platform,
            store_domain=token.store_domain,
            external_store_id=token.external_store_id,
            access_token_secret_ref=access_ref,
            webhook_secret_ref=webhook_ref,
            scopes=token.scopes,
        )

        delivery_url = f"{get_settings().public_api_base_url}/commerce/stores/{connection.id}/webhook"
        await adapter.register_webhooks(
            access_token=token.access_token, webhook_secret=token.webhook_secret, delivery_url=delivery_url
        )
        await self.refresh_capabilities(connection.id)

        await self._audit.record(
            event_type="commerce.store_connected",
            actor_type="user",
            actor_id=str(user_id),
            organization_id=organization_id,
            summary=f"Connected {platform} store '{token.external_account_name}'",
            payload={"connection_id": str(connection.id), "platform": platform},
        )
        await self._session.commit()
        return connection

    async def refresh_capabilities(self, connection_id: uuid.UUID) -> None:
        connection = await self._repo.get_connection_by_id(connection_id)
        assert connection is not None
        adapter = self._store_adapter_factory(connection.platform)
        access_token = await self._secrets.unseal(reference=connection.access_token_secret_ref)
        results = await adapter.resolve_capabilities(access_token=access_token)
        for result in results:
            await self._repo.upsert_capability(
                connection_id=connection.id,
                capability=result.capability,
                is_available=result.is_available,
                reason=result.reason,
            )
        await self._session.commit()

    async def disconnect_store(self, connection_id: uuid.UUID, *, user_id: uuid.UUID) -> None:
        connection = await self._repo.get_connection_by_id(connection_id)
        if connection is None:
            raise StoreNotFound(str(connection_id))

        # Best-effort — an unreachable OpenBao shouldn't block disconnecting
        # the store; a missing/already-gone secret is already tolerated
        # inside OpenBaoSecretsAdapter.delete() itself (404 is a no-op there).
        for ref in (connection.access_token_secret_ref, connection.webhook_secret_ref):
            try:
                await self._secrets.delete(reference=ref)
            except httpx.HTTPError:
                pass

        platform, store_domain = connection.platform, connection.store_domain
        organization_id = connection.organization_id
        await self._repo.delete_connection(connection)

        await self._audit.record(
            event_type="commerce.store_disconnected",
            actor_type="user",
            actor_id=str(user_id),
            organization_id=organization_id,
            summary=f"Disconnected {platform} store '{store_domain}'",
            payload={"connection_id": str(connection_id), "platform": platform},
        )
        await self._session.commit()

    async def sync_products(self, connection_id: uuid.UUID) -> SyncResult:
        connection = await self._repo.get_connection_by_id(connection_id)
        if connection is None:
            raise StoreNotFound(str(connection_id))
        adapter = self._store_adapter_factory(connection.platform)
        access_token = await self._secrets.unseal(reference=connection.access_token_secret_ref)

        cursor_row = await self._repo.get_sync_cursor(connection_id, "products")
        page = await adapter.list_products(access_token=access_token, cursor=cursor_row.cursor if cursor_row else None)

        for product_data in page.products:
            price = _to_decimal(product_data.price)
            product = await self._repo.upsert_product(
                organization_id=connection.organization_id,
                workspace_id=connection.workspace_id,
                store_connection_id=connection.id,
                external_product_id=product_data.external_product_id,
                title=product_data.title,
                description=product_data.description,
                price=price,
                currency=product_data.currency,
                status=product_data.status,
                raw_payload=product_data.raw_payload,
                categories=product_data.categories,
            )
            for variant in product_data.variants:
                await self._repo.upsert_variant(
                    product_id=product.id,
                    external_variant_id=variant.external_variant_id,
                    title=variant.title,
                    sku=variant.sku,
                    price=_to_decimal(variant.price),
                    raw_payload=variant.raw_payload,
                )
            for position, url in enumerate(product_data.image_urls):
                await self._repo.upsert_asset(
                    product_id=product.id,
                    external_asset_id=f"{product_data.external_product_id}-image-{position}",
                    url=url,
                    position=position,
                )

        await self._repo.set_sync_cursor(connection_id, "products", page.next_cursor)
        await self._repo.set_last_synced(connection)
        await self._audit.record(
            event_type="commerce.products_synced",
            actor_type="service",
            organization_id=connection.organization_id,
            summary=f"Synced {len(page.products)} product(s) from {connection.platform}",
            payload={"connection_id": str(connection_id), "products_synced": len(page.products)},
        )
        await self._session.commit()
        return SyncResult(products_synced=len(page.products), next_cursor=page.next_cursor)

    async def receive_webhook(
        self,
        *,
        connection_id: uuid.UUID,
        topic: str,
        raw_body: bytes,
        signature_header: str | None,
        external_delivery_id: str | None,
    ) -> WebhookResult:
        connection = await self._repo.get_connection_by_id(connection_id)
        if connection is None:
            raise StoreNotFound(str(connection_id))

        if external_delivery_id:
            existing = await self._repo.get_delivery_by_external_id(connection_id, external_delivery_id)
            if existing is not None:
                return WebhookResult(accepted=existing.signature_valid, delivery_id=str(existing.id))

        secret = await self._secrets.unseal(reference=connection.webhook_secret_ref)
        valid = verify_signature(raw_body, secret, signature_header)

        try:
            payload = json.loads(raw_body) if raw_body else {}
        except (json.JSONDecodeError, UnicodeDecodeError):
            payload = {}

        delivery = await self._repo.create_webhook_delivery(
            organization_id=connection.organization_id,
            workspace_id=connection.workspace_id,
            store_connection_id=connection.id,
            topic=topic,
            external_delivery_id=external_delivery_id,
            payload=payload,
            signature_valid=valid,
        )

        if valid:
            await self._repo.mark_delivery_processed(delivery)
            await self._audit.record(
                event_type="commerce.webhook_accepted",
                actor_type="service",
                organization_id=connection.organization_id,
                summary=f"Accepted {topic} webhook from {connection.platform}",
                payload={"connection_id": str(connection_id), "delivery_id": str(delivery.id), "topic": topic},
            )
            if topic.startswith("product."):
                # A verified product change is exactly what a store owner
                # expects to show up without them clicking "Sync now" — see
                # sync_products() for the actual pagination/upsert logic.
                await self.sync_products(connection_id)
        else:
            await self._audit.record(
                event_type="commerce.webhook_rejected",
                actor_type="service",
                organization_id=connection.organization_id,
                summary=f"Rejected {topic} webhook from {connection.platform}: signature mismatch",
                payload={"connection_id": str(connection_id), "delivery_id": str(delivery.id), "topic": topic},
            )

        await self._session.commit()
        return WebhookResult(accepted=valid, delivery_id=str(delivery.id))

    async def generate_product_campaign_brief(
        self,
        *,
        organization_id: uuid.UUID,
        workspace_id: uuid.UUID,
        user_id: uuid.UUID,
        product_id: uuid.UUID,
        goal_slug: str,
        mode: str,
        target_platforms: list[str],
    ) -> CampaignProposal:
        product = await self._get_workspace_product(product_id, workspace_id)
        what_to_promote = f"{_strip_product_size(product.title)} - {product.description}".strip(" -")

        marketing_service = MarketingService(self._session)
        brief = await marketing_service.create_brief(
            organization_id=organization_id, workspace_id=workspace_id, user_id=user_id, goal_slug=goal_slug,
            what_to_promote=what_to_promote, mode=mode, target_platforms=target_platforms,
        )
        proposal = await marketing_service.generate_proposal(brief.id)

        await self._audit.record(
            event_type="commerce.product_campaign_generated",
            actor_type="user",
            actor_id=str(user_id),
            organization_id=organization_id,
            summary=f"Generated a product campaign proposal for '{product.title}'",
            payload={"product_id": str(product_id), "proposal_id": str(proposal.id)},
        )
        await self._session.commit()
        return proposal

    async def build_bulk_plan_items(
        self,
        *,
        organization_id: uuid.UUID,
        workspace_id: uuid.UUID,
        user_id: uuid.UUID,
        product_ids: list[uuid.UUID],
        description: str,
        goal_slug: str,
        target_platforms: list[str],
        campaign_id: uuid.UUID | None,
        generate_images: bool,
    ) -> BulkCampaignResult:
        """The DB-writing half of the Quick Start bulk product flow — one
        text item (and optionally one image item) per product. Text briefs
        combine the product's own title, the workspace's persistent brand
        context (BrandProfile.product_line_description), this batch's
        shared `description`, and a style reference sampled once from the
        workspace's own recently-published Meta posts (best-effort — a
        missing connection or API failure just means no style reference,
        never blocks generation). Does NOT start Temporal workflows for the
        text items — same split as prepare_item_generation(), since
        starting N workflows concurrently needs to happen outside any
        single AsyncSession-bound call, at the API layer. Image items get
        even less here: only a bare "pending" CampaignPlanItem row, no
        ContentItem/GenerationJob at all — see prepare_paired_image_generation()
        for why (dispatch is deferred until the paired text is approved)."""
        marketing_service = MarketingService(self._session)
        marketing_repo = MarketingRepository(self._session)

        product_line_description = await self._get_product_line_description(workspace_id)
        recent_captions = await self._get_recent_post_captions(workspace_id)
        recent_rejection_feedback = await CreationRepository(self._session).list_recent_rejection_comments_for_workspace(
            workspace_id
        )

        campaign: Campaign
        if campaign_id is None:
            # Cheap and deterministic (no LLM call) — only needed to satisfy
            # Campaign.proposal_id's NOT NULL/UNIQUE constraint, not to
            # preview anything: at N=50 products there's nothing meaningful
            # to show as a single combined "proposal" anyway.
            brief = await marketing_service.create_brief(
                organization_id=organization_id, workspace_id=workspace_id, user_id=user_id, goal_slug=goal_slug,
                what_to_promote=description, mode="guided", target_platforms=target_platforms,
            )
            proposal = await marketing_service.generate_proposal(brief.id)
            campaign = await marketing_repo.create_campaign(
                organization_id=organization_id, workspace_id=workspace_id, proposal_id=proposal.id,
                approved_by_user_id=user_id, name=description.strip()[:60] or "Bulk product campaign",
            )
        else:
            existing_campaign = await marketing_repo.get_campaign_by_id(campaign_id)
            if existing_campaign is None or existing_campaign.workspace_id != workspace_id:
                raise CampaignNotFound(str(campaign_id))
            campaign = existing_campaign

        sequence_number = len(await marketing_repo.list_plan_items_for_campaign(campaign.id))
        target_platform = target_platforms[0] if target_platforms else None

        prepared_items: list[BulkPlanItemPrepared] = []
        failed_product_ids: list[uuid.UUID] = []
        for product_id in product_ids:
            # get_product_with_details_by_id (not get_product_by_id) — its
            # eager-loaded .assets is what makes the primary-photo lookup
            # below safe; a lazy relationship access raises MissingGreenlet
            # under the async engine.
            product = await self._repo.get_product_with_details_by_id(product_id)
            if product is None or product.workspace_id != workspace_id:
                failed_product_ids.append(product_id)
                continue

            sequence_number += 1
            content_title = _strip_product_size(product.title)
            text_brief = _build_text_brief(
                product_title=content_title, product_line_description=product_line_description,
                campaign_description=description, recent_captions=recent_captions,
                recent_rejection_feedback=recent_rejection_feedback,
            )
            text_item = await marketing_repo.create_plan_item(
                campaign_id=campaign.id, sequence_number=sequence_number, title=product.title,
                brief_text=text_brief, target_platform=target_platform,
                product_id=product.id, content_type="text",
            )
            prepared_items.append(
                BulkPlanItemPrepared(plan_item=text_item, prepared=await marketing_service.prepare_item_generation(text_item))
            )

            if generate_images:
                sequence_number += 1
                # Preview only — the brief actually used for generation is
                # rebuilt from scratch by prepare_paired_image_generation()
                # once the paired text item is approved, re-reading the
                # product's photo fresh at that point rather than trusting
                # whatever it looked like right now. No ContentItem/
                # GenerationJob/workflow starts for this item here — it
                # stays "pending" until that approval (or a manual Start,
                # gated the same way) dispatches it.
                reference_image_url = (
                    min(product.assets, key=lambda a: a.position).url if product.assets else None
                )
                image_brief = _build_image_edit_prompt(
                    product_title=content_title, campaign_description=description,
                    has_reference_image=reference_image_url is not None,
                )
                await marketing_repo.create_plan_item(
                    campaign_id=campaign.id, sequence_number=sequence_number, title=f"{product.title} (image)",
                    brief_text=image_brief, target_platform=target_platform,
                    product_id=product.id, content_type="image",
                )

        await self._audit.record(
            event_type="commerce.bulk_product_campaign_prepared",
            actor_type="user",
            actor_id=str(user_id),
            organization_id=organization_id,
            summary=(
                f"Prepared {len(prepared_items)} item(s) across "
                f"{len(product_ids) - len(failed_product_ids)} product(s)"
            ),
            payload={
                "campaign_id": str(campaign.id),
                "product_count": len(product_ids),
                "failed_count": len(failed_product_ids),
            },
        )
        await self._session.commit()
        return BulkCampaignResult(
            campaign_id=campaign.id, prepared_items=prepared_items, failed_product_ids=failed_product_ids
        )

    async def generate_abandoned_cart_content(
        self,
        *,
        organization_id: uuid.UUID,
        workspace_id: uuid.UUID,
        user_id: uuid.UUID,
        product_id: uuid.UUID,
        consent_confirmed: bool,
    ) -> CampaignProposal:
        if not consent_confirmed:
            await self._audit.record(
                event_type="commerce.abandoned_cart_content_refused_no_consent",
                actor_type="user",
                actor_id=str(user_id),
                organization_id=organization_id,
                summary="Refused to generate abandoned-cart content: customer consent not confirmed",
                payload={"product_id": str(product_id)},
            )
            await self._session.commit()
            raise ConsentRequired("Cannot generate abandoned-cart content without confirmed customer consent")

        product = await self._get_workspace_product(product_id, workspace_id)
        what_to_promote = f"Remind the customer about {_strip_product_size(product.title)}, which they left in their cart."

        marketing_service = MarketingService(self._session)
        brief = await marketing_service.create_brief(
            organization_id=organization_id, workspace_id=workspace_id, user_id=user_id,
            goal_slug=ABANDONED_CART_GOAL_SLUG, what_to_promote=what_to_promote, mode="guided", target_platforms=[],
        )
        proposal = await marketing_service.generate_proposal(brief.id)

        await self._audit.record(
            event_type="commerce.abandoned_cart_content_generated",
            actor_type="user",
            actor_id=str(user_id),
            organization_id=organization_id,
            summary=f"Generated consent-confirmed abandoned-cart content for '{product.title}'",
            payload={"product_id": str(product_id), "proposal_id": str(proposal.id)},
        )
        await self._session.commit()
        return proposal

    async def _get_workspace_product(self, product_id: uuid.UUID, workspace_id: uuid.UUID) -> Product:
        product = await self._repo.get_product_by_id(product_id)
        if product is None or product.workspace_id != workspace_id:
            raise ProductNotFound(str(product_id))
        return product

    async def _get_product_line_description(self, workspace_id: uuid.UUID) -> str | None:
        profiles = await IdentityRepository(self._session).list_brand_profiles_for_workspace(workspace_id)
        active = next((p for p in profiles if p.is_active), profiles[0] if profiles else None)
        return active.product_line_description if active else None

    async def _get_recent_post_captions(self, workspace_id: uuid.UUID, *, limit: int = 5) -> list[str]:
        # Best-effort style reference — no connection, an unreachable Meta
        # API, or a token that's since been revoked should just mean "no
        # style reference," never block content generation.
        try:
            connections = await PublishingRepository(self._session).list_connections_for_workspace(workspace_id)
            connection = next((c for c in connections if c.platform in ("facebook", "instagram")), None)
            if connection is None:
                return []
            adapter = get_social_platform_adapter(get_settings(), connection.platform)
            access_token = await self._secrets.unseal(reference=connection.access_token_secret_ref)
            posts = await adapter.list_recent_posts(
                access_token=access_token, external_account_id=connection.external_account_id, limit=limit
            )
            return [p.caption for p in posts if p.caption]
        except Exception:  # noqa: BLE001 — any failure here degrades to "no style reference"
            return []


def _to_decimal(value: str | None) -> Decimal | None:
    if value is None:
        return None
    return Decimal(value)


# Store product titles carry a weight suffix (e.g. "200γρ.") that's useful
# on the store listing but reads as clutter in a caption or image prompt —
# stripped before either goes into a generation brief.
_PRODUCT_SIZE_PATTERN = re.compile(r"\s*\d+\s?γρ\.?", re.IGNORECASE)


def _strip_product_size(title: str) -> str:
    return _PRODUCT_SIZE_PATTERN.sub("", title).strip().rstrip(".,-").strip()


def _build_text_brief(
    *,
    product_title: str,
    product_line_description: str | None,
    campaign_description: str,
    recent_captions: list[str],
    recent_rejection_feedback: list[str],
) -> str:
    lines = [
        f"Write a social media caption for: {product_title}.",
        (
            f'Name this specific product/scent ("{product_title}") clearly in the caption — '
            "don't write generic copy that could describe any product in the line."
        ),
    ]
    if product_line_description:
        lines.append(f"About our business: {product_line_description}")
    lines.append(f"This post should focus on: {campaign_description}")
    if recent_captions:
        lines.append("Match the tone and style of these recent posts we've published:")
        lines.extend(f"- {caption}" for caption in recent_captions[:3])
    if recent_rejection_feedback:
        lines.append("Avoid these previously flagged issues:")
        lines.extend(f"- {comment}" for comment in recent_rejection_feedback[:3])
    return "\n".join(lines)


def _build_image_edit_prompt(*, product_title: str, campaign_description: str, has_reference_image: bool) -> str:
    if has_reference_image:
        # The model already sees the real product photo — describing the
        # product again risks it drifting toward its own imagined version
        # instead of the one shown. Standard Kontext edit-prompt pattern:
        # state what to preserve, then what to change — and ground the
        # change in the product's own name/scent, not just the generic
        # campaign angle, so a "Whiskey Caramel" candle actually gets a
        # background that reads as whiskey-and-caramel, not an arbitrary one.
        return (
            f"Keep the product exactly as shown. Restyle the background to a scene that evokes "
            f"'{product_title}': {campaign_description}"
        )
    return f"{product_title}. {campaign_description}"


async def prepare_paired_image_generation(
    session: AsyncSession, image_plan_item: CampaignPlanItem
) -> PreparedGeneration | None:
    """Called when a bulk campaign's paired TEXT item is approved (or its
    image item is manually started) — deliberately re-reads the product's
    *current* synced photo and rebuilds the image brief from scratch,
    rather than trusting whatever build_bulk_plan_items() saw when the
    campaign was first created. That's the whole point of deferring this:
    a product photo synced after campaign creation (or changed since) is
    picked up correctly instead of silently generating a plain AI-imagined
    image. Returns None (never raises) when there's nothing sensible to
    dispatch — a deleted product or no active image recipe — so callers can
    just leave the plan item "pending" for a later retry."""
    if image_plan_item.product_id is None:
        return None

    commerce_repo = CommerceRepository(session)
    product = await commerce_repo.get_product_with_details_by_id(image_plan_item.product_id)
    if product is None:
        return None

    marketing_repo = MarketingRepository(session)
    campaign = await marketing_repo.get_campaign_by_id(image_plan_item.campaign_id)
    proposal = await marketing_repo.get_proposal_by_id(campaign.proposal_id) if campaign else None
    brief = await marketing_repo.get_brief_by_id(proposal.brief_id) if proposal else None
    campaign_description = brief.what_to_promote if brief else ""

    reference_image_url = min(product.assets, key=lambda a: a.position).url if product.assets else None
    image_brief = _build_image_edit_prompt(
        product_title=_strip_product_size(product.title), campaign_description=campaign_description,
        has_reference_image=reference_image_url is not None,
    )

    try:
        prepared = await MarketingService(session).prepare_item_generation(
            image_plan_item, reference_image_url=reference_image_url
        )
    except NoActiveRecipe:
        return None
    return replace(prepared, brief_text=image_brief)
