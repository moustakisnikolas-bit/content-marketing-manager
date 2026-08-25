from dataclasses import dataclass, field
from typing import Protocol


class StoreResponseError(RuntimeError):
    """A store's API returned a 2xx status but not the actual API response
    expected — seen in practice against a real store sitting behind
    Cloudflare-style bot protection, which can serve an HTML "checking
    your browser" interstitial with a 200 status instead of proxying the
    request through to the store platform. A bare status-code check can't
    tell that apart from a genuine successful response, so adapters must
    verify the body is actually parseable JSON before trusting a 2xx,
    raising this instead of silently treating the interstitial as success
    (which would otherwise mean *any* credentials, including wrong ones,
    "connect" successfully)."""


@dataclass(frozen=True)
class StoreOAuthToken:
    access_token: str
    external_store_id: str
    store_domain: str
    external_account_name: str
    scopes: list[str]
    webhook_secret: str


@dataclass(frozen=True)
class CapabilityResult:
    capability: str
    is_available: bool
    reason: str | None = None


@dataclass(frozen=True)
class VariantData:
    external_variant_id: str
    title: str
    price: str | None
    sku: str | None
    raw_payload: dict


@dataclass(frozen=True)
class ProductData:
    external_product_id: str
    title: str
    description: str
    price: str | None
    currency: str | None
    status: str
    raw_payload: dict
    image_urls: list[str] = field(default_factory=list)
    variants: list[VariantData] = field(default_factory=list)


@dataclass(frozen=True)
class ProductPage:
    products: list[ProductData]
    next_cursor: str | None


class StoreConnectorPort(Protocol):
    """Provider-neutral port for a connected store (WooCommerce or
    Shopify — the Phase 6 commitment from 12_ECOMMERCE_MANAGER_MODULE.md).
    Capabilities are always resolved through resolve_capabilities(), never
    hardcoded, same discipline as SocialPlatformPort. Webhook signature
    verification is deliberately NOT part of this port — it's pure HMAC
    crypto with no external I/O, so it lives as a plain function in
    modules/commerce/webhook_signature.py and is exercised for real even
    against the stub adapter."""

    def get_authorization_url(self, *, state: str) -> str: ...

    async def exchange_code_for_token(self, *, code: str) -> StoreOAuthToken: ...

    async def connect_with_credentials(
        self, *, store_domain: str, consumer_key: str, consumer_secret: str
    ) -> StoreOAuthToken:
        """Connect path for platforms with no OAuth2 code-exchange step at
        all — WooCommerce's REST API keys are generated manually by the
        store owner in their own WP Admin, not issued via a redirect. The
        returned StoreOAuthToken.access_token is this adapter's own opaque
        credential blob (same discipline as every other access_token in
        this port: sealed as-is by the caller, only ever round-tripped back
        to this same adapter, never inspected by the service layer) — for
        WooCommerce specifically it carries the store domain alongside the
        key pair, since list_products()/resolve_capabilities() have no
        separate store_domain parameter of their own."""
        ...

    async def resolve_capabilities(self, *, access_token: str) -> list[CapabilityResult]: ...

    async def list_products(self, *, access_token: str, cursor: str | None) -> ProductPage: ...

    async def register_webhooks(self, *, access_token: str, webhook_secret: str, delivery_url: str) -> bool:
        """Best-effort webhook auto-provisioning, called once the store's
        connection row exists (delivery_url embeds its id, so this can't
        happen inside connect_with_credentials()/exchange_code_for_token()
        — those run before the row is created). Returns whether at least
        one webhook was actually registered; platforms with nothing to do
        here (or that provision webhooks as part of their OAuth grant
        already) can just return True unconditionally."""
        ...
