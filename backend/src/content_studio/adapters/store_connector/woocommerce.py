import asyncio
import json
import uuid
from html.parser import HTMLParser
from typing import Any
from urllib.parse import urlparse

import httpx

from content_studio.config import Settings
from content_studio.ports.store_connector import (
    CapabilityResult,
    ProductData,
    ProductPage,
    StoreOAuthToken,
    StoreResponseError,
    VariantData,
)

_STATUS_MAP = {"publish": "active", "draft": "draft"}
_PAGE_SIZE = 20
_WEBHOOK_TOPICS = ("product.created", "product.updated", "product.deleted")


class _TextExtractor(HTMLParser):
    """Strips WooCommerce's raw HTML/shortcode-laden product descriptions
    down to plain text. Needed because this text flows into moderation-
    scanned AI campaign generation (mcp/tools/ecommerce.py treats product
    title/description as untrusted input) — nothing downstream expects or
    sanitizes markup."""

    def __init__(self) -> None:
        super().__init__()
        self._chunks: list[str] = []

    def handle_data(self, data: str) -> None:
        self._chunks.append(data)

    def text(self) -> str:
        return " ".join(" ".join(self._chunks).split())


def _strip_html(raw: str) -> str:
    parser = _TextExtractor()
    parser.feed(raw)
    return parser.text()


def _encode_credentials(*, store_domain: str, consumer_key: str, consumer_secret: str) -> str:
    return json.dumps(
        {"store_domain": store_domain, "consumer_key": consumer_key, "consumer_secret": consumer_secret}
    )


def _decode_credentials(access_token: str) -> tuple[str, str, str]:
    data = json.loads(access_token)
    return data["store_domain"], data["consumer_key"], data["consumer_secret"]


def _require_json(response: httpx.Response) -> Any:
    """raise_for_status() only catches 4xx/5xx — a store behind bot
    protection can return 200 with an HTML challenge page instead of the
    real API response, which would otherwise be silently treated as
    success (see StoreResponseError's docstring). Use this instead of a
    bare raise_for_status() anywhere the caller needs to trust the result,
    not just the status code."""
    response.raise_for_status()
    try:
        return response.json()
    except ValueError as exc:
        raise StoreResponseError(
            f"Store returned a non-JSON response (HTTP {response.status_code}) from "
            f"{response.url} — this can happen when a firewall or bot-protection "
            "service (e.g. Cloudflare) blocks the request before it reaches "
            "WooCommerce. Check the store's security settings allow API requests "
            "from this server."
        ) from exc


def _is_json_response(response: httpx.Response) -> bool:
    """Soft version of _require_json for capability checks, which report
    unavailable rather than raise."""
    if response.status_code != 200:
        return False
    try:
        response.json()
    except ValueError:
        return False
    return True


class WooCommerceAdapter:
    """Real WooCommerce REST API v3 adapter. Unlike Meta/Shopify's OAuth2
    flow, WooCommerce credentials (a Consumer Key/Secret pair) are
    generated manually by the store owner in their own WP Admin — there is
    no code-exchange step, so this adapter is driven entirely through
    connect_with_credentials(), not get_authorization_url()/
    exchange_code_for_token(). access_token is this adapter's own opaque
    JSON blob carrying store_domain + the key pair, since list_products()/
    resolve_capabilities() have no separate store_domain parameter."""

    def __init__(self, settings: Settings) -> None:
        del settings  # no app-level config needed — credentials are per-connection

    def get_authorization_url(self, *, state: str) -> str:
        raise NotImplementedError("WooCommerce has no OAuth2 redirect flow — use connect_with_credentials")

    async def exchange_code_for_token(self, *, code: str) -> StoreOAuthToken:
        raise NotImplementedError("WooCommerce has no OAuth2 redirect flow — use connect_with_credentials")

    async def connect_with_credentials(
        self, *, store_domain: str, consumer_key: str, consumer_secret: str
    ) -> StoreOAuthToken:
        base = store_domain.rstrip("/")
        auth = (consumer_key, consumer_secret)
        async with httpx.AsyncClient(timeout=httpx.Timeout(connect=10, read=30, write=10, pool=10)) as client:
            response = await client.get(f"{base}/wp-json/wc/v3/products", params={"per_page": 1}, auth=auth)
            _require_json(response)

        return StoreOAuthToken(
            access_token=_encode_credentials(
                store_domain=base, consumer_key=consumer_key, consumer_secret=consumer_secret
            ),
            external_store_id=urlparse(base).netloc or f"woocommerce-{uuid.uuid4().hex[:8]}",
            store_domain=base,
            external_account_name=urlparse(base).netloc or base,
            scopes=["read_products"],
            webhook_secret=uuid.uuid4().hex,
        )

    async def register_webhooks(self, *, access_token: str, webhook_secret: str, delivery_url: str) -> bool:
        store_domain, consumer_key, consumer_secret = _decode_credentials(access_token)
        base = store_domain.rstrip("/")
        auth = (consumer_key, consumer_secret)

        async def _register_one(client: httpx.AsyncClient, topic: str) -> bool:
            try:
                response = await client.post(
                    f"{base}/wp-json/wc/v3/webhooks",
                    auth=auth,
                    json={
                        "name": f"content-studio-{topic}",
                        "topic": topic,
                        "delivery_url": delivery_url,
                        "secret": webhook_secret,
                    },
                )
                _require_json(response)
                return True
            except (httpx.HTTPError, StoreResponseError):
                # Best-effort — product sync still works via the
                # manual/on-demand "Sync now" path even if webhook
                # auto-provisioning fails (insufficient key scope, etc).
                return False

        # Concurrent, not sequential — each topic is an independent HTTP
        # round-trip to the store's own REST API, and stores sitting behind
        # bot-protection/WAF interstitials (see windows-dev-gotchas #23-#24)
        # can make each one individually slow; run one-after-another and the
        # cumulative wait can exceed callers' own timeouts (confirmed live:
        # the WooCommerce plugin's connect request timed out at 20s against
        # ceri.gr with this sequential, even though nothing was broken).
        async with httpx.AsyncClient(timeout=httpx.Timeout(connect=10, read=30, write=10, pool=10)) as client:
            results = await asyncio.gather(*(_register_one(client, topic) for topic in _WEBHOOK_TOPICS))
        return any(results)

    async def resolve_capabilities(self, *, access_token: str) -> list[CapabilityResult]:
        store_domain, consumer_key, consumer_secret = _decode_credentials(access_token)
        base = store_domain.rstrip("/")
        auth = (consumer_key, consumer_secret)

        async with httpx.AsyncClient(timeout=httpx.Timeout(connect=10, read=30, write=10, pool=10)) as client:
            products_response = await client.get(f"{base}/wp-json/wc/v3/products", params={"per_page": 1}, auth=auth)
            read_products = _is_json_response(products_response)

            orders_response = await client.get(f"{base}/wp-json/wc/v3/orders", params={"per_page": 1}, auth=auth)
            read_orders = _is_json_response(orders_response)

        return [
            CapabilityResult(capability="read_products", is_available=read_products),
            CapabilityResult(
                capability="read_orders",
                is_available=read_orders,
                reason=None if read_orders else "Requires the 'Read/Write' REST API key scope",
            ),
        ]

    async def list_products(self, *, access_token: str, cursor: str | None) -> ProductPage:
        store_domain, consumer_key, consumer_secret = _decode_credentials(access_token)
        base = store_domain.rstrip("/")
        auth = (consumer_key, consumer_secret)
        page = int(cursor) if cursor else 1

        async with httpx.AsyncClient(timeout=httpx.Timeout(connect=10, read=30, write=10, pool=10)) as client:
            response = await client.get(
                f"{base}/wp-json/wc/v3/products", params={"page": page, "per_page": _PAGE_SIZE}, auth=auth
            )
            raw_products = _require_json(response)

            products = []
            for raw in raw_products:
                variants: list[VariantData] = []
                if raw.get("type") == "variable":
                    variations_response = await client.get(
                        f"{base}/wp-json/wc/v3/products/{raw['id']}/variations",
                        params={"per_page": 100},
                        auth=auth,
                    )
                    if variations_response.status_code == 200:
                        variants = [
                            VariantData(
                                external_variant_id=str(v["id"]),
                                title=v.get("sku") or f"Variant {v['id']}",
                                price=v.get("price") or None,
                                sku=v.get("sku") or None,
                                raw_payload=v,
                            )
                            for v in variations_response.json()
                        ]

                products.append(
                    ProductData(
                        external_product_id=str(raw["id"]),
                        title=raw.get("name", ""),
                        description=_strip_html(raw.get("description") or raw.get("short_description") or ""),
                        price=raw.get("price") or None,
                        currency=None,  # WooCommerce's product resource doesn't carry a per-product currency
                        status=_STATUS_MAP.get(raw.get("status", ""), "archived"),
                        raw_payload=raw,
                        image_urls=[img["src"] for img in raw.get("images", []) if img.get("src")],
                        variants=variants,
                    )
                )

            total_pages = int(response.headers.get("X-WP-TotalPages", "1"))
            next_cursor = str(page + 1) if page < total_pages else None
            return ProductPage(products=products, next_cursor=next_cursor)
