import uuid
from datetime import UTC, datetime
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from content_studio.modules.commerce.models import (
    Product,
    ProductAsset,
    ProductPerformanceSnapshot,
    ProductVariant,
    StoreCapability,
    StoreConnection,
    StoreSyncCursor,
    StoreWebhookDelivery,
)


class CommerceRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    # -- Store connections --------------------------------------------

    async def create_connection(
        self,
        *,
        organization_id: uuid.UUID,
        workspace_id: uuid.UUID,
        connected_by_user_id: uuid.UUID,
        platform: str,
        store_domain: str,
        external_store_id: str,
        access_token_secret_ref: str,
        webhook_secret_ref: str,
        scopes: list[str],
    ) -> StoreConnection:
        connection = StoreConnection(
            organization_id=organization_id,
            workspace_id=workspace_id,
            connected_by_user_id=connected_by_user_id,
            platform=platform,
            store_domain=store_domain,
            external_store_id=external_store_id,
            access_token_secret_ref=access_token_secret_ref,
            webhook_secret_ref=webhook_secret_ref,
            scopes=scopes,
        )
        self._session.add(connection)
        await self._session.flush()
        return connection

    async def get_connection_by_id(self, connection_id: uuid.UUID) -> StoreConnection | None:
        return await self._session.get(StoreConnection, connection_id)

    async def list_connections_for_workspace(self, workspace_id: uuid.UUID) -> list[StoreConnection]:
        result = await self._session.execute(
            select(StoreConnection).where(StoreConnection.workspace_id == workspace_id)
        )
        return list(result.scalars().all())

    async def set_last_synced(self, connection: StoreConnection) -> None:
        connection.last_synced_at = datetime.now(UTC)
        await self._session.flush()

    # -- Capabilities --------------------------------------------

    async def upsert_capability(
        self, *, connection_id: uuid.UUID, capability: str, is_available: bool, reason: str | None
    ) -> StoreCapability:
        result = await self._session.execute(
            select(StoreCapability).where(
                StoreCapability.store_connection_id == connection_id, StoreCapability.capability == capability
            )
        )
        existing = result.scalar_one_or_none()
        now = datetime.now(UTC)
        if existing is not None:
            existing.is_available = is_available
            existing.reason = reason
            existing.resolved_at = now
            await self._session.flush()
            return existing

        row = StoreCapability(
            store_connection_id=connection_id, capability=capability, is_available=is_available, reason=reason,
            resolved_at=now,
        )
        self._session.add(row)
        await self._session.flush()
        return row

    async def list_capabilities_for_connection(self, connection_id: uuid.UUID) -> list[StoreCapability]:
        result = await self._session.execute(
            select(StoreCapability).where(StoreCapability.store_connection_id == connection_id)
        )
        return list(result.scalars().all())

    async def get_capability(self, connection_id: uuid.UUID, capability: str) -> StoreCapability | None:
        result = await self._session.execute(
            select(StoreCapability).where(
                StoreCapability.store_connection_id == connection_id, StoreCapability.capability == capability
            )
        )
        return result.scalar_one_or_none()

    # -- Sync cursor --------------------------------------------

    async def get_sync_cursor(self, connection_id: uuid.UUID, resource_type: str) -> StoreSyncCursor | None:
        result = await self._session.execute(
            select(StoreSyncCursor).where(
                StoreSyncCursor.store_connection_id == connection_id, StoreSyncCursor.resource_type == resource_type
            )
        )
        return result.scalar_one_or_none()

    async def set_sync_cursor(self, connection_id: uuid.UUID, resource_type: str, cursor: str | None) -> None:
        existing = await self.get_sync_cursor(connection_id, resource_type)
        now = datetime.now(UTC)
        if existing is not None:
            existing.cursor = cursor
            existing.last_synced_at = now
            await self._session.flush()
            return
        row = StoreSyncCursor(
            store_connection_id=connection_id, resource_type=resource_type, cursor=cursor, last_synced_at=now
        )
        self._session.add(row)
        await self._session.flush()

    # -- Products --------------------------------------------

    async def upsert_product(
        self,
        *,
        organization_id: uuid.UUID,
        workspace_id: uuid.UUID,
        store_connection_id: uuid.UUID,
        external_product_id: str,
        title: str,
        description: str,
        price: Decimal | None,
        currency: str | None,
        status: str,
        raw_payload: dict,
    ) -> Product:
        result = await self._session.execute(
            select(Product).where(
                Product.store_connection_id == store_connection_id,
                Product.external_product_id == external_product_id,
            )
        )
        existing = result.scalar_one_or_none()
        now = datetime.now(UTC)
        if existing is not None:
            existing.title = title
            existing.description = description
            existing.price = price
            existing.currency = currency
            existing.status = status
            existing.raw_payload = raw_payload
            existing.synced_at = now
            await self._session.flush()
            return existing

        product = Product(
            organization_id=organization_id, workspace_id=workspace_id, store_connection_id=store_connection_id,
            external_product_id=external_product_id, title=title, description=description, price=price,
            currency=currency, status=status, raw_payload=raw_payload, synced_at=now,
        )
        self._session.add(product)
        await self._session.flush()
        return product

    async def get_product_by_id(self, product_id: uuid.UUID) -> Product | None:
        return await self._session.get(Product, product_id)

    async def get_product_with_details_by_id(self, product_id: uuid.UUID) -> Product | None:
        """Eager-loads variants/assets — plain lazy access on an unloaded
        relationship raises MissingGreenlet under the async engine, so any
        caller that needs them (the product detail API) must go through
        this, not get_product_by_id()."""
        result = await self._session.execute(
            select(Product)
            .where(Product.id == product_id)
            .options(selectinload(Product.variants), selectinload(Product.assets))
        )
        return result.scalar_one_or_none()

    async def list_products_for_workspace(self, workspace_id: uuid.UUID) -> list[Product]:
        result = await self._session.execute(
            select(Product).where(Product.workspace_id == workspace_id).order_by(Product.synced_at.desc())
        )
        return list(result.scalars().all())

    async def list_products_for_connection(self, connection_id: uuid.UUID) -> list[Product]:
        result = await self._session.execute(
            select(Product).where(Product.store_connection_id == connection_id).order_by(Product.title)
        )
        return list(result.scalars().all())

    # -- Variants & assets --------------------------------------------

    async def upsert_variant(
        self,
        *,
        product_id: uuid.UUID,
        external_variant_id: str,
        title: str,
        sku: str | None,
        price: Decimal | None,
        raw_payload: dict,
    ) -> ProductVariant:
        result = await self._session.execute(
            select(ProductVariant).where(
                ProductVariant.product_id == product_id, ProductVariant.external_variant_id == external_variant_id
            )
        )
        existing = result.scalar_one_or_none()
        if existing is not None:
            existing.title = title
            existing.sku = sku
            existing.price = price
            existing.raw_payload = raw_payload
            await self._session.flush()
            return existing

        variant = ProductVariant(
            product_id=product_id, external_variant_id=external_variant_id, title=title, sku=sku, price=price,
            raw_payload=raw_payload,
        )
        self._session.add(variant)
        await self._session.flush()
        return variant

    async def upsert_asset(
        self, *, product_id: uuid.UUID, external_asset_id: str, url: str, position: int
    ) -> ProductAsset:
        result = await self._session.execute(
            select(ProductAsset).where(
                ProductAsset.product_id == product_id, ProductAsset.external_asset_id == external_asset_id
            )
        )
        existing = result.scalar_one_or_none()
        if existing is not None:
            existing.url = url
            existing.position = position
            await self._session.flush()
            return existing

        asset = ProductAsset(product_id=product_id, external_asset_id=external_asset_id, url=url, position=position)
        self._session.add(asset)
        await self._session.flush()
        return asset

    # -- Webhook deliveries --------------------------------------------

    async def create_webhook_delivery(
        self,
        *,
        organization_id: uuid.UUID,
        workspace_id: uuid.UUID,
        store_connection_id: uuid.UUID,
        topic: str,
        external_delivery_id: str | None,
        payload: dict,
        signature_valid: bool,
    ) -> StoreWebhookDelivery:
        delivery = StoreWebhookDelivery(
            organization_id=organization_id, workspace_id=workspace_id, store_connection_id=store_connection_id,
            topic=topic, external_delivery_id=external_delivery_id, payload=payload,
            signature_valid=signature_valid, received_at=datetime.now(UTC),
        )
        self._session.add(delivery)
        await self._session.flush()
        return delivery

    async def get_delivery_by_external_id(
        self, store_connection_id: uuid.UUID, external_delivery_id: str
    ) -> StoreWebhookDelivery | None:
        result = await self._session.execute(
            select(StoreWebhookDelivery).where(
                StoreWebhookDelivery.store_connection_id == store_connection_id,
                StoreWebhookDelivery.external_delivery_id == external_delivery_id,
            )
        )
        return result.scalar_one_or_none()

    async def mark_delivery_processed(self, delivery: StoreWebhookDelivery, *, error: str | None = None) -> None:
        delivery.processed_at = datetime.now(UTC)
        delivery.processing_error = error
        await self._session.flush()

    async def list_deliveries_for_connection(self, connection_id: uuid.UUID) -> list[StoreWebhookDelivery]:
        result = await self._session.execute(
            select(StoreWebhookDelivery)
            .where(StoreWebhookDelivery.store_connection_id == connection_id)
            .order_by(StoreWebhookDelivery.received_at.desc())
        )
        return list(result.scalars().all())

    # -- Product performance --------------------------------------------

    async def create_performance_snapshot(
        self,
        *,
        organization_id: uuid.UUID,
        workspace_id: uuid.UUID,
        product_id: uuid.UUID,
        metric_name: str,
        raw_provider_name: str,
        raw_payload: dict,
        normalized_value: Decimal,
        measurement_time: datetime,
        collection_time: datetime,
    ) -> ProductPerformanceSnapshot:
        snapshot = ProductPerformanceSnapshot(
            organization_id=organization_id, workspace_id=workspace_id, product_id=product_id,
            metric_name=metric_name, raw_provider_name=raw_provider_name, raw_payload=raw_payload,
            normalized_value=normalized_value, measurement_time=measurement_time, collection_time=collection_time,
        )
        self._session.add(snapshot)
        await self._session.flush()
        return snapshot
