import uuid
from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, Field


class AuthorizationUrlOut(BaseModel):
    authorization_url: str


class ConnectWithCredentialsRequest(BaseModel):
    platform: str = Field(pattern="^(woocommerce)$")
    store_domain: str = Field(min_length=1, max_length=500)
    consumer_key: str = Field(min_length=1, max_length=500)
    consumer_secret: str = Field(min_length=1, max_length=500)


class PluginPairingCodeOut(BaseModel):
    pairing_token: str
    expires_in_minutes: int


class ConnectViaPluginRequest(BaseModel):
    pairing_token: str
    store_domain: str = Field(min_length=1, max_length=500)
    consumer_key: str = Field(min_length=1, max_length=500)
    consumer_secret: str = Field(min_length=1, max_length=500)


class CapabilityOut(BaseModel):
    capability: str
    is_available: bool
    reason: str | None

    model_config = {"from_attributes": True}


class StoreConnectionOut(BaseModel):
    id: uuid.UUID
    platform: str
    store_domain: str
    status: str
    last_synced_at: datetime | None
    created_at: datetime

    model_config = {"from_attributes": True}


class ConnectionDetailOut(BaseModel):
    connection: StoreConnectionOut
    capabilities: list[CapabilityOut]


class SyncProductsResponse(BaseModel):
    products_synced: int
    next_cursor: str | None
    categories_synced: int = 0


class CategoryOut(BaseModel):
    id: uuid.UUID
    external_category_id: str
    name: str
    # The store's own parent category id (matches another row's
    # external_category_id), not an internal uuid — the frontend builds
    # the tree from this flat list itself.
    parent_external_category_id: str | None

    model_config = {"from_attributes": True}


class ProductVariantOut(BaseModel):
    id: uuid.UUID
    title: str
    sku: str | None
    price: Decimal | None

    model_config = {"from_attributes": True}


class ProductAssetOut(BaseModel):
    url: str
    position: int

    model_config = {"from_attributes": True}


class ProductOut(BaseModel):
    id: uuid.UUID
    store_connection_id: uuid.UUID
    title: str
    description: str
    price: Decimal | None
    currency: str | None
    status: str
    categories: list[str]
    synced_at: datetime

    model_config = {"from_attributes": True}


class ProductDetailOut(BaseModel):
    product: ProductOut
    variants: list[ProductVariantOut]
    assets: list[ProductAssetOut]


class GenerateProductCampaignRequest(BaseModel):
    goal_slug: str
    mode: str = Field(pattern="^(manual|guided|autopilot)$")
    target_platforms: list[str] = Field(default_factory=list)


class BulkProductCampaignRequest(BaseModel):
    product_ids: list[uuid.UUID] = Field(min_length=1, max_length=500)
    description: str = Field(min_length=1, max_length=2000)
    goal_slug: str
    target_platforms: list[str] = Field(default_factory=list)
    campaign_id: uuid.UUID | None = None
    generate_images: bool = True


class BulkProductCampaignResponse(BaseModel):
    campaign_id: uuid.UUID
    started_count: int
    failed_product_ids: list[uuid.UUID]


class GenerateAbandonedCartContentRequest(BaseModel):
    consent_confirmed: bool = False


class CampaignProposalOut(BaseModel):
    id: uuid.UUID
    brief_id: uuid.UUID
    objective: str
    assumptions: list[str]
    plan_summary: str
    plan_items_draft: list[dict]
    estimated_cost: Decimal
    explanation: str
    status: str

    model_config = {"from_attributes": True}


class WebhookReceivedOut(BaseModel):
    accepted: bool
    delivery_id: str
