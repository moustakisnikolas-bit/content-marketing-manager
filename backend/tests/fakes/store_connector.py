import uuid

from content_studio.ports.store_connector import (
    CapabilityResult,
    CategoryPage,
    ProductData,
    ProductPage,
    StoreOAuthToken,
)


class FakeStoreConnector:
    """In-memory StoreConnectorPort implementation with configurable
    capabilities and product pages, for exercising the capability-resolve
    and sync pagination paths deterministically."""

    def __init__(
        self,
        *,
        capabilities: list[CapabilityResult] | None = None,
        pages: list[ProductPage] | None = None,
        category_pages: list[CategoryPage] | None = None,
        webhook_secret: str = "fake-webhook-secret",
    ) -> None:
        self.capabilities = capabilities or [
            CapabilityResult(capability="read_products", is_available=True),
            CapabilityResult(capability="receive_webhooks", is_available=True),
        ]
        self._pages = pages
        self._category_pages = category_pages
        self.webhook_secret = webhook_secret

    def get_authorization_url(self, *, state: str) -> str:
        return f"https://fake-store-oauth.test/authorize?state={state}"

    async def exchange_code_for_token(self, *, code: str) -> StoreOAuthToken:
        return StoreOAuthToken(
            access_token="fake-store-access-token",
            external_store_id=f"fake-store-{uuid.uuid4().hex[:8]}",
            store_domain="fake-store.example.test",
            external_account_name="Fake Store",
            scopes=["read_products"],
            webhook_secret=self.webhook_secret,
        )

    async def connect_with_credentials(
        self, *, store_domain: str, consumer_key: str, consumer_secret: str
    ) -> StoreOAuthToken:
        return StoreOAuthToken(
            access_token="fake-store-access-token",
            external_store_id=f"fake-store-{uuid.uuid4().hex[:8]}",
            store_domain=store_domain,
            external_account_name="Fake Store",
            scopes=["read_products"],
            webhook_secret=self.webhook_secret,
        )

    async def resolve_capabilities(self, *, access_token: str) -> list[CapabilityResult]:
        return self.capabilities

    async def register_webhooks(self, *, access_token: str, webhook_secret: str, delivery_url: str) -> bool:
        return True

    async def list_products(self, *, access_token: str, cursor: str | None) -> ProductPage:
        if self._pages is not None:
            offset = int(cursor) if cursor else 0
            return self._pages[offset]

        product = ProductData(
            external_product_id="fake-product-1",
            title="Fake Product",
            description="A fake product for tests.",
            price="10.00",
            currency="USD",
            status="active",
            raw_payload={"title": "Fake Product"},
            image_urls=["https://fake-cdn.test/image.jpg"],
            variants=[],
        )
        return ProductPage(products=[product], next_cursor=None)

    async def list_categories(self, *, access_token: str, cursor: str | None) -> CategoryPage:
        if self._category_pages is not None:
            offset = int(cursor) if cursor else 0
            return self._category_pages[offset]
        return CategoryPage(categories=[], next_cursor=None)
