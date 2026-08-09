import hashlib
import secrets
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError

from content_studio.config import get_settings

# Deliberately not cached into a module-level variable: get_settings() is
# itself lru_cache'd, but reading it here at import time would pin whatever
# environment was present when this module was FIRST imported (e.g. during
# pytest collection, before test fixtures set CS_DATABASE_URL) — see
# tests/conftest.py's _migrated_schema fixture for the failure mode this
# caused.
_hasher = PasswordHasher()


def hash_password(plain_password: str) -> str:
    return _hasher.hash(plain_password)


def verify_password(plain_password: str, hashed_password: str) -> bool:
    try:
        return _hasher.verify(hashed_password, plain_password)
    except VerifyMismatchError:
        return False


def create_access_token(user_id: uuid.UUID, organization_id: uuid.UUID | None = None) -> str:
    settings = get_settings()
    now = datetime.now(UTC)
    payload: dict[str, Any] = {
        "sub": str(user_id),
        "iat": now,
        "exp": now + timedelta(minutes=settings.access_token_ttl_minutes),
        "type": "access",
    }
    if organization_id is not None:
        payload["org"] = str(organization_id)
    return jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)


def decode_access_token(token: str) -> dict[str, Any]:
    settings = get_settings()
    return jwt.decode(token, settings.jwt_secret, algorithms=[settings.jwt_algorithm])


def generate_refresh_token() -> tuple[str, str, datetime]:
    """Returns (raw_token_for_client, sha256_hash_for_storage, expires_at).
    Only the hash is ever persisted, matching the rule that Redis (not used
    here) and Postgres never store recoverable secrets in plaintext."""
    raw = secrets.token_urlsafe(48)
    token_hash = hashlib.sha256(raw.encode("utf-8")).hexdigest()
    expires_at = datetime.now(UTC) + timedelta(days=get_settings().refresh_token_ttl_days)
    return raw, token_hash, expires_at


def hash_refresh_token(raw_token: str) -> str:
    return hashlib.sha256(raw_token.encode("utf-8")).hexdigest()


def generate_opaque_token(*, prefix: str) -> tuple[str, str, str]:
    """General-purpose opaque secret generator, shared by Invitation and
    ApiKey (RefreshToken keeps its own generate_refresh_token() above,
    which additionally computes an expiry). Returns
    (raw_token_for_one_time_display, sha256_hash_for_storage,
    display_prefix) — only the hash is ever persisted; the prefix lets a
    user recognize a key in a list without the full secret being
    recoverable from storage."""
    raw_suffix = secrets.token_urlsafe(32)
    raw = f"{prefix}_{raw_suffix}"
    token_hash = hashlib.sha256(raw.encode("utf-8")).hexdigest()
    display_prefix = f"{prefix}_{raw_suffix[:8]}"
    return raw, token_hash, display_prefix
