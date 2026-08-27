import uuid

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from content_studio.api.deps import (
    WorkspaceContext,
    get_current_user,
    get_db_session,
    get_secrets,
    get_store_adapter,
    get_workspace_context,
)
from content_studio.config import get_settings
from content_studio.modules.commerce.exceptions import (
    ConsentRequired,
    ProductNotFound,
    StoreNotFound,
)
from content_studio.modules.commerce.repository import CommerceRepository
from content_studio.modules.commerce.schemas import (
    AuthorizationUrlOut,
    CampaignProposalOut,
    CapabilityOut,
    ConnectionDetailOut,
    ConnectViaPluginRequest,
    ConnectWithCredentialsRequest,
    GenerateAbandonedCartContentRequest,
    GenerateProductCampaignRequest,
    PluginPairingCodeOut,
    ProductAssetOut,
    ProductDetailOut,
    ProductOut,
    ProductVariantOut,
    StoreConnectionOut,
    SyncProductsResponse,
    WebhookReceivedOut,
)
from content_studio.modules.commerce.service import CommerceService
from content_studio.modules.identity.models import User
from content_studio.modules.publishing.exceptions import InvalidOAuthState
from content_studio.modules.publishing.oauth_state import (
    create_oauth_state,
    create_plugin_pairing_token,
    decode_oauth_state,
    decode_plugin_pairing_token,
)
from content_studio.ports.secrets import SecretsPort
from content_studio.ports.store_connector import StoreConnectorPort, StoreResponseError

router = APIRouter(prefix="/commerce", tags=["commerce"])


def _adapter_factory(platform: str) -> StoreConnectorPort:
    return get_store_adapter(platform)


async def _connection_detail(repo: CommerceRepository, connection) -> ConnectionDetailOut:
    capabilities = await repo.list_capabilities_for_connection(connection.id)
    return ConnectionDetailOut(
        connection=StoreConnectionOut.model_validate(connection),
        capabilities=[CapabilityOut.model_validate(c) for c in capabilities],
    )


@router.get("/oauth/authorize", response_model=AuthorizationUrlOut)
async def get_authorization_url(
    platform: str,
    current_user: User = Depends(get_current_user),
    context: WorkspaceContext = Depends(get_workspace_context),
) -> AuthorizationUrlOut:
    if platform not in ("woocommerce", "shopify"):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, f"Unsupported platform {platform!r}")

    state = create_oauth_state(
        organization_id=context.organization_id, workspace_id=context.workspace_id, user_id=current_user.id,
        platform=platform,
    )
    adapter = get_store_adapter(platform)
    return AuthorizationUrlOut(authorization_url=adapter.get_authorization_url(state=state))


@router.get("/oauth/callback", response_model=ConnectionDetailOut)
async def oauth_callback(
    code: str,
    state: str,
    session: AsyncSession = Depends(get_db_session),
    secrets: SecretsPort = Depends(get_secrets),
) -> ConnectionDetailOut:
    """No Bearer auth — a store's OAuth redirect can't carry our
    Authorization header, so the signed `state` param carries who's
    connecting what, same as publishing/oauth/callback."""
    try:
        claims = decode_oauth_state(state)
    except InvalidOAuthState as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc

    platform = claims["platform"]
    service = CommerceService(session, secrets=secrets, store_adapter_factory=_adapter_factory)
    connection = await service.connect_store(
        organization_id=uuid.UUID(claims["organization_id"]), workspace_id=uuid.UUID(claims["workspace_id"]),
        user_id=uuid.UUID(claims["user_id"]), platform=platform, code=code,
    )

    repo = CommerceRepository(session)
    return await _connection_detail(repo, connection)


@router.post("/connect/api-key", response_model=ConnectionDetailOut, status_code=status.HTTP_201_CREATED)
async def connect_with_api_key(
    body: ConnectWithCredentialsRequest,
    current_user: User = Depends(get_current_user),
    context: WorkspaceContext = Depends(get_workspace_context),
    session: AsyncSession = Depends(get_db_session),
    secrets: SecretsPort = Depends(get_secrets),
) -> ConnectionDetailOut:
    """Connect path for platforms with no OAuth2 redirect at all —
    WooCommerce's REST API keys are generated manually by the store owner
    in their own WP Admin, so this is a plain Bearer-authed request, not a
    redirect/callback dance (there's no external state to protect with
    oauth_state here)."""
    service = CommerceService(session, secrets=secrets, store_adapter_factory=_adapter_factory)
    try:
        connection = await service.connect_store_with_credentials(
            organization_id=context.organization_id, workspace_id=context.workspace_id, user_id=current_user.id,
            platform=body.platform, store_domain=body.store_domain, consumer_key=body.consumer_key,
            consumer_secret=body.consumer_secret,
        )
    except (httpx.HTTPStatusError, StoreResponseError) as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, f"Could not verify store credentials: {exc}") from exc

    repo = CommerceRepository(session)
    return await _connection_detail(repo, connection)


@router.post("/connect/plugin-pairing-code", response_model=PluginPairingCodeOut)
async def create_plugin_pairing_code(
    current_user: User = Depends(get_current_user),
    context: WorkspaceContext = Depends(get_workspace_context),
) -> PluginPairingCodeOut:
    """Generated from the logged-in web app and pasted into the WooCommerce
    plugin's settings screen — the plugin runs server-side on the store's
    own hosting with no browser session, so this signed token is the only
    thing telling it which workspace to attach a connection to."""
    token = create_plugin_pairing_token(
        organization_id=context.organization_id, workspace_id=context.workspace_id, user_id=current_user.id,
    )
    return PluginPairingCodeOut(pairing_token=token, expires_in_minutes=30)


@router.post("/connect/plugin", response_model=ConnectionDetailOut, status_code=status.HTTP_201_CREATED)
async def connect_via_plugin(
    body: ConnectViaPluginRequest,
    session: AsyncSession = Depends(get_db_session),
    secrets: SecretsPort = Depends(get_secrets),
) -> ConnectionDetailOut:
    """Called by the WooCommerce plugin itself (wp_remote_post from the
    store's own server), not a logged-in browser — no Bearer auth, same
    reasoning as /oauth/callback. The plugin generates its own WooCommerce
    API key pair internally and sends it here alongside the pairing token
    it was given; everything past validating that token reuses
    connect_store_with_credentials exactly as the manual-form path does."""
    try:
        claims = decode_plugin_pairing_token(body.pairing_token)
    except InvalidOAuthState as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc

    service = CommerceService(session, secrets=secrets, store_adapter_factory=_adapter_factory)
    try:
        connection = await service.connect_store_with_credentials(
            organization_id=uuid.UUID(claims["organization_id"]), workspace_id=uuid.UUID(claims["workspace_id"]),
            user_id=uuid.UUID(claims["user_id"]), platform="woocommerce", store_domain=body.store_domain,
            consumer_key=body.consumer_key, consumer_secret=body.consumer_secret,
        )
    except (httpx.HTTPStatusError, StoreResponseError) as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, f"Could not verify store credentials: {exc}") from exc

    repo = CommerceRepository(session)
    return await _connection_detail(repo, connection)


@router.get("/stores", response_model=list[ConnectionDetailOut])
async def list_stores(
    context: WorkspaceContext = Depends(get_workspace_context), session: AsyncSession = Depends(get_db_session)
) -> list[ConnectionDetailOut]:
    repo = CommerceRepository(session)
    connections = await repo.list_connections_for_workspace(context.workspace_id)
    return [await _connection_detail(repo, c) for c in connections]


@router.delete("/stores/{connection_id}", status_code=status.HTTP_204_NO_CONTENT)
async def disconnect_store(
    connection_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    context: WorkspaceContext = Depends(get_workspace_context),
    session: AsyncSession = Depends(get_db_session),
    secrets: SecretsPort = Depends(get_secrets),
) -> None:
    repo = CommerceRepository(session)
    connection = await repo.get_connection_by_id(connection_id)
    if connection is None or connection.workspace_id != context.workspace_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Store connection not found")

    service = CommerceService(session, secrets=secrets, store_adapter_factory=_adapter_factory)
    await service.disconnect_store(connection_id, user_id=current_user.id)


@router.post("/stores/{connection_id}/sync", response_model=SyncProductsResponse)
async def sync_products(
    connection_id: uuid.UUID,
    context: WorkspaceContext = Depends(get_workspace_context),
    session: AsyncSession = Depends(get_db_session),
    secrets: SecretsPort = Depends(get_secrets),
) -> SyncProductsResponse:
    repo = CommerceRepository(session)
    connection = await repo.get_connection_by_id(connection_id)
    if connection is None or connection.workspace_id != context.workspace_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Store connection not found")

    service = CommerceService(session, secrets=secrets, store_adapter_factory=_adapter_factory)
    result = await service.sync_products(connection_id)
    return SyncProductsResponse(products_synced=result.products_synced, next_cursor=result.next_cursor)


@router.get("/stores/{connection_id}/products", response_model=list[ProductOut])
async def list_products_for_store(
    connection_id: uuid.UUID,
    context: WorkspaceContext = Depends(get_workspace_context),
    session: AsyncSession = Depends(get_db_session),
) -> list[ProductOut]:
    repo = CommerceRepository(session)
    connection = await repo.get_connection_by_id(connection_id)
    if connection is None or connection.workspace_id != context.workspace_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Store connection not found")
    products = await repo.list_products_for_connection(connection_id)
    return [ProductOut.model_validate(p) for p in products]


@router.get("/products", response_model=list[ProductOut])
async def list_products(
    context: WorkspaceContext = Depends(get_workspace_context), session: AsyncSession = Depends(get_db_session)
) -> list[ProductOut]:
    repo = CommerceRepository(session)
    products = await repo.list_products_for_workspace(context.workspace_id)
    return [ProductOut.model_validate(p) for p in products]


@router.get("/products/{product_id}", response_model=ProductDetailOut)
async def get_product(
    product_id: uuid.UUID,
    context: WorkspaceContext = Depends(get_workspace_context),
    session: AsyncSession = Depends(get_db_session),
) -> ProductDetailOut:
    repo = CommerceRepository(session)
    product = await repo.get_product_with_details_by_id(product_id)
    if product is None or product.workspace_id != context.workspace_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Product not found")
    return ProductDetailOut(
        product=ProductOut.model_validate(product),
        variants=[ProductVariantOut.model_validate(v) for v in product.variants],
        assets=[ProductAssetOut.model_validate(a) for a in sorted(product.assets, key=lambda a: a.position)],
    )


@router.post("/products/{product_id}/campaign", response_model=CampaignProposalOut, status_code=status.HTTP_201_CREATED)
async def generate_product_campaign(
    product_id: uuid.UUID,
    body: GenerateProductCampaignRequest,
    current_user: User = Depends(get_current_user),
    context: WorkspaceContext = Depends(get_workspace_context),
    session: AsyncSession = Depends(get_db_session),
    secrets: SecretsPort = Depends(get_secrets),
) -> CampaignProposalOut:
    service = CommerceService(session, secrets=secrets, store_adapter_factory=_adapter_factory)
    try:
        proposal = await service.generate_product_campaign_brief(
            organization_id=context.organization_id, workspace_id=context.workspace_id, user_id=current_user.id,
            product_id=product_id, goal_slug=body.goal_slug, mode=body.mode, target_platforms=body.target_platforms,
        )
    except ProductNotFound as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Product not found") from exc
    return CampaignProposalOut.model_validate(proposal)


@router.post(
    "/products/{product_id}/abandoned-cart-content",
    response_model=CampaignProposalOut,
    status_code=status.HTTP_201_CREATED,
)
async def generate_abandoned_cart_content(
    product_id: uuid.UUID,
    body: GenerateAbandonedCartContentRequest,
    current_user: User = Depends(get_current_user),
    context: WorkspaceContext = Depends(get_workspace_context),
    session: AsyncSession = Depends(get_db_session),
    secrets: SecretsPort = Depends(get_secrets),
) -> CampaignProposalOut:
    service = CommerceService(session, secrets=secrets, store_adapter_factory=_adapter_factory)
    try:
        proposal = await service.generate_abandoned_cart_content(
            organization_id=context.organization_id, workspace_id=context.workspace_id, user_id=current_user.id,
            product_id=product_id, consent_confirmed=body.consent_confirmed,
        )
    except ConsentRequired as exc:
        raise HTTPException(status.HTTP_403_FORBIDDEN, str(exc)) from exc
    except ProductNotFound as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Product not found") from exc
    return CampaignProposalOut.model_validate(proposal)


@router.post("/stores/{connection_id}/webhook", response_model=WebhookReceivedOut)
async def receive_webhook(
    connection_id: uuid.UUID,
    request: Request,
    session: AsyncSession = Depends(get_db_session),
    secrets: SecretsPort = Depends(get_secrets),
) -> WebhookReceivedOut:
    """No Bearer auth — this is called by the store itself (WooCommerce/
    Shopify), authenticated only by the HMAC signature header, exactly like
    a real webhook receiver. The raw body must be read before any JSON
    parsing since the signature is computed over the exact bytes sent."""
    settings = get_settings()
    topic = request.headers.get("x-wc-webhook-topic") or request.headers.get("x-shopify-topic") or "unknown"
    signature = request.headers.get("x-wc-webhook-signature") or request.headers.get("x-shopify-hmac-sha256")
    delivery_id = request.headers.get("x-shopify-webhook-id") or request.headers.get("x-wc-webhook-delivery-id")
    raw_body = await request.body()
    if len(raw_body) > settings.max_webhook_body_bytes:
        raise HTTPException(status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, "Webhook payload too large")

    service = CommerceService(session, secrets=secrets, store_adapter_factory=_adapter_factory)
    try:
        result = await service.receive_webhook(
            connection_id=connection_id, topic=topic, raw_body=raw_body, signature_header=signature,
            external_delivery_id=delivery_id,
        )
    except StoreNotFound as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Store connection not found") from exc
    return WebhookReceivedOut(accepted=result.accepted, delivery_id=result.delivery_id)
