import uuid

from content_studio.ports.store_connector import (
    CapabilityResult,
    ProductData,
    ProductPage,
    StoreOAuthToken,
    VariantData,
)

# Same rationale as adapters/social_platform/stub.py: real WooCommerce REST
# API / Shopify Admin API adapters need a live store + registered app this
# dev environment doesn't have, deferred per docs/adr/. The stub keeps the
# full connect -> capability-resolve -> sync -> webhook lifecycle testable.
_PLATFORM_CAPABILITIES: dict[str, dict[str, str | None]] = {
    "woocommerce": {
        "read_products": None,
        "receive_webhooks": None,
        "read_orders": "Requires the 'Read/Write' REST API key scope, not granted for this store connection",
    },
    "shopify": {"read_products": None, "receive_webhooks": None, "read_orders": None},
}

_PAGE_SIZE = 2

_CATALOG_TEMPLATE = [
    ("Classic Tote Bag", "Durable canvas tote for everyday use.", "24.00", ["classic-tote-1", "classic-tote-2"]),
    ("Ceramic Mug", "Hand-glazed ceramic mug, 350ml.", "14.50", ["ceramic-mug-1"]),
    ("Wool Beanie", "Warm wool beanie, one size fits most.", "19.00", ["wool-beanie-1"]),
    ("Leather Wallet", "Slim bifold wallet in full-grain leather.", "39.00", ["leather-wallet-1", "leather-wallet-2"]),
    ("Enamel Pin Set", "Set of 3 enamel pins.", "9.00", ["enamel-pins-1"]),
]


class StubStoreConnectorAdapter:
    """Dev-mode fallback used when no real WooCommerce/Shopify app is
    configured. A fixed, deterministic catalog so sync/pagination behavior
    is genuinely exercisable and reproducible across test runs."""

    def __init__(self, platform: str) -> None:
        self._platform = platform

    def get_authorization_url(self, *, state: str) -> str:
        return f"https://stub-oauth.local/{self._platform}/authorize?state={state}"

    async def exchange_code_for_token(self, *, code: str) -> StoreOAuthToken:
        store_id = f"stub-{self._platform}-{uuid.uuid4().hex[:8]}"
        domain = f"{store_id}.example.test"
        return StoreOAuthToken(
            access_token=f"stub-store-access-token-{uuid.uuid4().hex}",
            external_store_id=store_id,
            store_domain=domain,
            external_account_name=f"Demo {self._platform.title()} Store",
            scopes=["read_products", "read_orders"],
            webhook_secret=f"stub-webhook-secret-{uuid.uuid4().hex}",
        )

    async def connect_with_credentials(
        self, *, store_domain: str, consumer_key: str, consumer_secret: str
    ) -> StoreOAuthToken:
        store_id = f"stub-{self._platform}-{uuid.uuid4().hex[:8]}"
        return StoreOAuthToken(
            access_token=f"stub-store-access-token-{uuid.uuid4().hex}",
            external_store_id=store_id,
            store_domain=store_domain,
            external_account_name=f"Demo {self._platform.title()} Store",
            scopes=["read_products", "read_orders"],
            webhook_secret=f"stub-webhook-secret-{uuid.uuid4().hex}",
        )

    async def resolve_capabilities(self, *, access_token: str) -> list[CapabilityResult]:
        capabilities = _PLATFORM_CAPABILITIES.get(self._platform, {})
        return [
            CapabilityResult(capability=name, is_available=reason is None, reason=reason)
            for name, reason in capabilities.items()
        ]

    async def register_webhooks(self, *, access_token: str, webhook_secret: str, delivery_url: str) -> bool:
        return True

    async def list_products(self, *, access_token: str, cursor: str | None) -> ProductPage:
        offset = int(cursor) if cursor else 0
        page = _CATALOG_TEMPLATE[offset : offset + _PAGE_SIZE]

        products = [
            ProductData(
                external_product_id=f"{self._platform}-product-{offset + i}",
                title=title,
                description=description,
                price=price,
                currency="USD",
                status="active",
                raw_payload={"title": title, "description": description, "price": price, "platform": self._platform},
                image_urls=[f"https://stub-cdn.local/{self._platform}/{img}.jpg" for img in images],
                variants=[
                    VariantData(
                        external_variant_id=f"{self._platform}-product-{offset + i}-default",
                        title="Default",
                        price=price,
                        sku=f"SKU-{offset + i}",
                        raw_payload={"title": "Default", "price": price},
                    )
                ],
            )
            for i, (title, description, price, images) in enumerate(page)
        ]

        next_offset = offset + _PAGE_SIZE
        next_cursor = str(next_offset) if next_offset < len(_CATALOG_TEMPLATE) else None
        return ProductPage(products=products, next_cursor=next_cursor)
