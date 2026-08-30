import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Numeric,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from content_studio.db.base import Base, TenantScopedMixin, TimestampMixin, UUIDPrimaryKeyMixin

# Two store platforms this phase commits to, per 12_ECOMMERCE_MANAGER_MODULE.md
# — a thin WooCommerce plugin and a thin Shopify app, neither carrying any
# AI logic or provider keys on the store's own infrastructure.
STORE_PLATFORMS = ("woocommerce", "shopify")

STORE_CONNECTION_STATUSES = ("connected", "disconnected", "error", "token_expired")

PRODUCT_STATUSES = ("active", "draft", "archived")


class StoreConnection(UUIDPrimaryKeyMixin, TimestampMixin, TenantScopedMixin, Base):
    """A connected WooCommerce or Shopify store. Tokens and the webhook
    signing secret are never stored in plaintext — only opaque references
    into OpenBao, same discipline as PlatformConnection in the publishing
    module."""

    __tablename__ = "store_connections"
    __table_args__ = (
        ForeignKeyConstraint(
            ["organization_id"], ["organizations.id"], ondelete="CASCADE",
            name="fk_store_connections_organization_id_organizations",
        ),
        CheckConstraint(f"platform in {STORE_PLATFORMS}", name="ck_store_connection_platform"),
        CheckConstraint(f"status in {STORE_CONNECTION_STATUSES}", name="ck_store_connection_status"),
    )

    workspace_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False, index=True
    )
    connected_by_user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    platform: Mapped[str] = mapped_column(String(20), nullable=False)
    store_domain: Mapped[str] = mapped_column(String(300), nullable=False)
    external_store_id: Mapped[str] = mapped_column(String(200), nullable=False)
    access_token_secret_ref: Mapped[str] = mapped_column(String(300), nullable=False)
    webhook_secret_ref: Mapped[str] = mapped_column(String(300), nullable=False)
    scopes: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="connected")
    last_synced_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # passive_deletes=True: without it, SQLAlchemy's ORM tries to manage
    # this relationship itself on delete by UPDATE-ing each child's FK to
    # NULL first, which fails against store_connection_id's NOT NULL
    # constraint — confirmed live via a real test. This defers entirely to
    # the DB's own ondelete="CASCADE" on that FK instead.
    capabilities: Mapped[list["StoreCapability"]] = relationship(back_populates="connection", passive_deletes=True)


class StoreCapability(UUIDPrimaryKeyMixin, Base):
    """Dynamically resolved per connection, never hardcoded — same pattern
    as EffectiveCapability in the publishing module (a store's actual
    plan/app permissions determine what's available, not our assumptions)."""

    __tablename__ = "store_capabilities"
    __table_args__ = (
        UniqueConstraint("store_connection_id", "capability", name="uq_store_capability_conn_cap"),
    )

    store_connection_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("store_connections.id", ondelete="CASCADE"), nullable=False, index=True
    )
    capability: Mapped[str] = mapped_column(String(100), nullable=False)
    is_available: Mapped[bool] = mapped_column(Boolean, nullable=False)
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    resolved_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    connection: Mapped["StoreConnection"] = relationship(back_populates="capabilities")


class StoreSyncCursor(UUIDPrimaryKeyMixin, Base):
    """One row per (connection, resource_type) — makes product sync
    incremental and idempotent instead of a full catalog re-pull every
    time."""

    __tablename__ = "store_sync_cursors"
    __table_args__ = (
        UniqueConstraint("store_connection_id", "resource_type", name="uq_store_sync_cursor_conn_resource"),
    )

    store_connection_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("store_connections.id", ondelete="CASCADE"), nullable=False, index=True
    )
    resource_type: Mapped[str] = mapped_column(String(50), nullable=False)
    cursor: Mapped[str | None] = mapped_column(String(500), nullable=True)
    last_synced_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class Product(UUIDPrimaryKeyMixin, TimestampMixin, TenantScopedMixin, Base):
    """A synced product. raw_payload keeps the provider-native response
    verbatim, per the same dual-storage discipline used for metrics — the
    handful of normalized columns are what content generation actually
    reads, the raw payload is what a future field mapping change can fall
    back to without re-syncing."""

    __tablename__ = "products"
    __table_args__ = (
        ForeignKeyConstraint(
            ["organization_id"], ["organizations.id"], ondelete="CASCADE",
            name="fk_products_organization_id_organizations",
        ),
        UniqueConstraint("store_connection_id", "external_product_id", name="uq_product_conn_external_id"),
        CheckConstraint(f"status in {PRODUCT_STATUSES}", name="ck_product_status"),
    )

    workspace_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False, index=True
    )
    store_connection_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("store_connections.id", ondelete="CASCADE"), nullable=False, index=True
    )
    external_product_id: Mapped[str] = mapped_column(String(200), nullable=False)
    title: Mapped[str] = mapped_column(String(500), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")
    price: Mapped[Decimal | None] = mapped_column(Numeric(12, 2), nullable=True)
    currency: Mapped[str | None] = mapped_column(String(3), nullable=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="active")
    raw_payload: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    categories: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list)
    synced_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    variants: Mapped[list["ProductVariant"]] = relationship(back_populates="product")
    assets: Mapped[list["ProductAsset"]] = relationship(back_populates="product")


class ProductVariant(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "product_variants"
    __table_args__ = (
        UniqueConstraint("product_id", "external_variant_id", name="uq_variant_product_external_id"),
    )

    product_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("products.id", ondelete="CASCADE"), nullable=False, index=True
    )
    external_variant_id: Mapped[str] = mapped_column(String(200), nullable=False)
    title: Mapped[str] = mapped_column(String(300), nullable=False)
    sku: Mapped[str | None] = mapped_column(String(200), nullable=True)
    price: Mapped[Decimal | None] = mapped_column(Numeric(12, 2), nullable=True)
    raw_payload: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)

    product: Mapped["Product"] = relationship(back_populates="variants")


class ProductAsset(UUIDPrimaryKeyMixin, Base):
    """Reference to a provider-hosted product image. This phase links to
    the store's own image URL rather than re-hosting it in our object
    storage — importing into SeaweedFS is a natural follow-up once content
    generation needs to composite over product photos."""

    __tablename__ = "product_assets"
    __table_args__ = (
        UniqueConstraint("product_id", "external_asset_id", name="uq_asset_product_external_id"),
    )

    product_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("products.id", ondelete="CASCADE"), nullable=False, index=True
    )
    external_asset_id: Mapped[str] = mapped_column(String(200), nullable=False)
    url: Mapped[str] = mapped_column(Text, nullable=False)
    position: Mapped[int] = mapped_column(nullable=False, default=0)

    product: Mapped["Product"] = relationship(back_populates="assets")


class ProductPerformanceSnapshot(UUIDPrimaryKeyMixin, TenantScopedMixin, Base):
    """Append-only, dual raw+normalized storage for store-reported product
    performance (views, add-to-carts, purchases) — same shape as the
    analytics module's MetricSnapshot, kept self-contained in this module
    rather than a cross-module FK onto analytics.metric_definitions, since
    product metrics aren't yet part of that catalog."""

    __tablename__ = "product_performance_snapshots"
    __table_args__ = (
        ForeignKeyConstraint(
            ["organization_id"], ["organizations.id"], ondelete="CASCADE",
            name="fk_product_perf_snapshots_organization_id_organizations",
        ),
    )

    workspace_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False, index=True
    )
    product_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("products.id", ondelete="CASCADE"), nullable=False, index=True
    )
    metric_name: Mapped[str] = mapped_column(String(100), nullable=False)
    raw_provider_name: Mapped[str] = mapped_column(String(100), nullable=False)
    raw_payload: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    normalized_value: Mapped[Decimal] = mapped_column(Numeric(18, 6), nullable=False)
    measurement_time: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    collection_time: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class StoreWebhookDelivery(UUIDPrimaryKeyMixin, TenantScopedMixin, Base):
    """Append-only log of every inbound webhook, valid or not. Rejected
    (signature_valid=False) deliveries are recorded, never processed — the
    audit trail for 'why didn't this webhook do anything' has to include
    the ones we refused, not just the ones we accepted."""

    __tablename__ = "store_webhook_deliveries"
    __table_args__ = (
        ForeignKeyConstraint(
            ["organization_id"], ["organizations.id"], ondelete="CASCADE",
            name="fk_store_webhook_deliveries_organization_id_organizations",
        ),
    )

    workspace_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False, index=True
    )
    store_connection_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("store_connections.id", ondelete="CASCADE"), nullable=False, index=True
    )
    topic: Mapped[str] = mapped_column(String(100), nullable=False)
    external_delivery_id: Mapped[str | None] = mapped_column(String(200), nullable=True)
    payload: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    signature_valid: Mapped[bool] = mapped_column(Boolean, nullable=False)
    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    processed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    processing_error: Mapped[str | None] = mapped_column(Text, nullable=True)
