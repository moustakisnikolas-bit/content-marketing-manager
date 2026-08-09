import uuid
from datetime import UTC, datetime, timedelta

import jwt

from content_studio.config import get_settings
from content_studio.modules.publishing.exceptions import InvalidOAuthState

_STATE_TTL_MINUTES = 10


def create_oauth_state(*, organization_id: uuid.UUID, workspace_id: uuid.UUID, user_id: uuid.UUID, platform: str) -> str:
    """The OAuth `state` param is the only thing a platform's redirect
    carries back to our callback — it must be self-contained (no Bearer
    header survives the redirect), so it's a short-lived signed JWT rather
    than a bare random token needing server-side session storage."""
    settings = get_settings()
    now = datetime.now(UTC)
    payload = {
        "type": "oauth_state",
        "organization_id": str(organization_id),
        "workspace_id": str(workspace_id),
        "user_id": str(user_id),
        "platform": platform,
        "iat": now,
        "exp": now + timedelta(minutes=_STATE_TTL_MINUTES),
    }
    return jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)


def decode_oauth_state(token: str) -> dict:
    settings = get_settings()
    try:
        payload = jwt.decode(token, settings.jwt_secret, algorithms=[settings.jwt_algorithm])
    except jwt.PyJWTError as exc:
        raise InvalidOAuthState(str(exc)) from exc
    if payload.get("type") != "oauth_state":
        raise InvalidOAuthState("not an oauth_state token")
    return payload


def create_pending_connection_token(
    *, organization_id: uuid.UUID, workspace_id: uuid.UUID, user_id: uuid.UUID, platform: str,
    user_token_secret_ref: str,
) -> str:
    """Carries a *temporarily* sealed user-level access token (see
    PublishingService.PendingAccountSelection) from the OAuth callback
    response through to /oauth/select-page — same short-lived-signed-JWT
    discipline as create_oauth_state, just carrying a secret reference
    instead of raw identity claims (the actual token value stays sealed in
    OpenBao the whole time, never touches the browser)."""
    settings = get_settings()
    now = datetime.now(UTC)
    payload = {
        "type": "pending_connection",
        "organization_id": str(organization_id),
        "workspace_id": str(workspace_id),
        "user_id": str(user_id),
        "platform": platform,
        "user_token_secret_ref": user_token_secret_ref,
        "iat": now,
        "exp": now + timedelta(minutes=_STATE_TTL_MINUTES),
    }
    return jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)


def decode_pending_connection_token(token: str) -> dict:
    settings = get_settings()
    try:
        payload = jwt.decode(token, settings.jwt_secret, algorithms=[settings.jwt_algorithm])
    except jwt.PyJWTError as exc:
        raise InvalidOAuthState(str(exc)) from exc
    if payload.get("type") != "pending_connection":
        raise InvalidOAuthState("not a pending_connection token")
    return payload
