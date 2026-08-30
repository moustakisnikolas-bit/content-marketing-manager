import uuid
from collections.abc import AsyncIterator
from dataclasses import dataclass

import jwt
from fastapi import Depends, Header, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession
from temporalio.client import Client

from content_studio.adapters.factory import (
    get_policy_adapter,
    get_secrets_adapter,
    get_social_platform_adapter,
    get_store_connector_adapter,
)
from content_studio.adapters.object_storage.seaweedfs import SeaweedFSObjectStorage
from content_studio.config import get_settings
from content_studio.db.session import get_session
from content_studio.modules.billing.repository import BillingRepository
from content_studio.modules.identity import security
from content_studio.modules.identity.api_key_service import ApiKeyService
from content_studio.modules.identity.models import User
from content_studio.modules.identity.permissions import has_permission
from content_studio.modules.identity.repository import IdentityRepository
from content_studio.ports.object_storage import ObjectStoragePort
from content_studio.ports.policy import PolicyPort
from content_studio.ports.secrets import SecretsPort
from content_studio.ports.social_platform import SocialPlatformPort
from content_studio.ports.store_connector import StoreConnectorPort
from content_studio.rate_limit import RateLimiter, get_redis_client
from content_studio.workflows.client import get_temporal_client

_bearer_scheme = HTTPBearer(auto_error=False)
WORKSPACE_ID_HEADER = "X-Workspace-Id"
API_KEY_HEADER = "X-Api-Key"
PUBLIC_API_RATE_LIMIT_PER_MINUTE = 60


async def get_db_session() -> AsyncIterator[AsyncSession]:
    async for session in get_session():
        yield session


async def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer_scheme),
    session: AsyncSession = Depends(get_db_session),
) -> User:
    if credentials is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Missing bearer token")
    try:
        payload = security.decode_access_token(credentials.credentials)
    except jwt.PyJWTError as exc:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid or expired token") from exc

    user_id = uuid.UUID(payload["sub"])
    repo = IdentityRepository(session)
    user = await repo.get_user_by_id(user_id)
    if user is None or not user.is_active:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "User not found or inactive")
    return user


@dataclass(frozen=True)
class WorkspaceContext:
    organization_id: uuid.UUID
    workspace_id: uuid.UUID
    subscription_id: uuid.UUID
    role_permissions: list[str]


async def get_workspace_context(
    request: Request,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_session),
) -> WorkspaceContext:
    """Resolves the active workspace: the caller's first membership by
    default (unchanged behavior for every pre-Phase-8 caller), or an
    explicit X-Workspace-Id header — the multi-workspace switcher this
    module's own docstring flagged as a natural Phase 8 extension.
    Requesting a workspace the caller has no Membership in is a 403, not a
    404 — same tenant-isolation discipline as every Repository-layer
    query, just enforced one layer up."""
    identity_repo = IdentityRepository(session)
    memberships = await identity_repo.get_memberships_for_user(current_user.id)
    if not memberships:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "User has no workspace membership")

    requested = request.headers.get(WORKSPACE_ID_HEADER)
    if requested:
        try:
            requested_id = uuid.UUID(requested)
        except ValueError as exc:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "Invalid X-Workspace-Id header") from exc
        membership = next((m for m in memberships if m.workspace_id == requested_id), None)
        if membership is None:
            raise HTTPException(status.HTTP_403_FORBIDDEN, "You do not have access to this workspace")
    else:
        membership = memberships[0]

    workspace = await identity_repo.get_workspace_by_id(membership.workspace_id)
    role = await identity_repo.get_role_by_id(membership.role_id)
    assert workspace is not None and role is not None

    billing_repo = BillingRepository(session)
    subscription = await billing_repo.get_subscription_for_organization(workspace.organization_id)
    if subscription is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Organization has no active subscription")

    return WorkspaceContext(
        organization_id=workspace.organization_id,
        workspace_id=workspace.id,
        subscription_id=subscription.id,
        role_permissions=role.permissions,
    )


def require_permission(permission: str):
    """Dependency factory: gate an endpoint on a permission string, per
    Role.permissions. '*' (Owner) always passes. Applied to Phase 8's own
    new endpoints (workspace/invitation/api-key/branding management) —
    retrofitting this onto every pre-existing endpoint is a separate,
    larger effort deliberately out of scope here."""

    async def _check(context: WorkspaceContext = Depends(get_workspace_context)) -> WorkspaceContext:
        if not has_permission(context.role_permissions, permission):
            raise HTTPException(status.HTTP_403_FORBIDDEN, f"Missing required permission: {permission}")
        return context

    return _check


@dataclass(frozen=True)
class ApiKeyContext:
    organization_id: uuid.UUID
    workspace_id: uuid.UUID
    scopes: list[str]


def get_rate_limiter() -> RateLimiter:
    return RateLimiter(get_redis_client(get_settings().redis_url))


async def get_api_key_context(
    request: Request,
    session: AsyncSession = Depends(get_db_session),
    rate_limiter: RateLimiter = Depends(get_rate_limiter),
    x_api_key: str | None = Header(default=None, alias=API_KEY_HEADER),
) -> ApiKeyContext:
    """Auth for the public API (api/v1/public.py) — a workspace-scoped
    ApiKey instead of a user's JWT bearer token, rate-limited per key via
    Redis. This is the 'authenticated host injects tenant context' pattern
    from Phase 7 applied to machine callers: the key, not the request
    body, determines organization_id/workspace_id."""
    if not x_api_key:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Missing X-Api-Key header")

    api_key_service = ApiKeyService(session)
    api_key = await api_key_service.authenticate(x_api_key)
    if api_key is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid or revoked API key")

    result = await rate_limiter.check_and_increment(str(api_key.id), limit=PUBLIC_API_RATE_LIMIT_PER_MINUTE)
    if not result.allowed:
        raise HTTPException(
            status.HTTP_429_TOO_MANY_REQUESTS, f"Rate limit exceeded — retry in {result.reset_seconds}s",
            headers={"Retry-After": str(result.reset_seconds)},
        )

    return ApiKeyContext(organization_id=api_key.organization_id, workspace_id=api_key.workspace_id, scopes=api_key.scopes)


_object_storage: ObjectStoragePort | None = None


def get_object_storage() -> ObjectStoragePort:
    """Process-wide singleton — the boto3 client (and its one-time bucket
    check) is expensive to build and safe to share across requests, unlike
    the per-request DB session."""
    global _object_storage
    if _object_storage is None:
        _object_storage = SeaweedFSObjectStorage(get_settings())
    return _object_storage


_secrets: SecretsPort | None = None


def get_secrets() -> SecretsPort:
    global _secrets
    if _secrets is None:
        _secrets = get_secrets_adapter(get_settings())
    return _secrets


def get_platform_adapter(platform: str) -> SocialPlatformPort:
    return get_social_platform_adapter(get_settings(), platform)


def get_store_adapter(platform: str) -> StoreConnectorPort:
    return get_store_connector_adapter(get_settings(), platform)


_policy: PolicyPort | None = None


def get_policy() -> PolicyPort:
    global _policy
    if _policy is None:
        _policy = get_policy_adapter(get_settings())
    return _policy


def rate_limit_by_client_ip(*, action: str, limit: int, window_seconds: int = 60):
    """Dependency factory for unauthenticated endpoints (login/signup) that
    have no user or API key to key a rate limit by — falls back to the
    caller's IP, same Redis-backed RateLimiter as the public API's
    per-key limiting (see rate_limit.py). Coarser than per-key limiting
    (shared NAT/proxies mean multiple real users can share an IP), so the
    limits here are deliberately more generous than the public API's."""

    async def _check(request: Request) -> None:
        client_host = request.client.host if request.client else "unknown"
        limiter = RateLimiter(get_redis_client(get_settings().redis_url))
        result = await limiter.check_and_increment(f"{action}:{client_host}", limit=limit, window_seconds=window_seconds)
        if not result.allowed:
            raise HTTPException(
                status.HTTP_429_TOO_MANY_REQUESTS, f"Too many attempts — retry in {result.reset_seconds}s",
                headers={"Retry-After": str(result.reset_seconds)},
            )

    return _check


async def get_temporal_client_dep() -> Client:
    return await get_temporal_client()
