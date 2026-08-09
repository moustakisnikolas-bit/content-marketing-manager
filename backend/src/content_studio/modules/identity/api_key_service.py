import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from content_studio.modules.governance.service import AuditService
from content_studio.modules.identity import security
from content_studio.modules.identity.exceptions import ApiKeyNotFound
from content_studio.modules.identity.models import ApiKey
from content_studio.modules.identity.repository import IdentityRepository


class ApiKeyService:
    """Public-API credential lifecycle. Only ever handles the raw key at
    creation time — every other operation works off the hash, matching
    RefreshToken/Invitation's discipline. Authentication (authenticate())
    is the counterpart to get_current_user() for JWT bearer auth, used by
    the public API's own auth dependency (see api/deps.py's
    get_api_key_context)."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self._repo = IdentityRepository(session)
        self._audit = AuditService(session)

    async def create_api_key(
        self,
        *,
        organization_id: uuid.UUID,
        workspace_id: uuid.UUID,
        created_by_user_id: uuid.UUID,
        name: str,
        scopes: list[str],
    ) -> tuple[ApiKey, str]:
        raw_key, key_hash, key_prefix = security.generate_opaque_token(prefix="csk")
        api_key = await self._repo.create_api_key(
            organization_id=organization_id, workspace_id=workspace_id, created_by_user_id=created_by_user_id,
            name=name, key_prefix=key_prefix, key_hash=key_hash, scopes=scopes,
        )
        await self._audit.record(
            event_type="identity.api_key_created",
            actor_type="user",
            actor_id=str(created_by_user_id),
            organization_id=organization_id,
            summary=f"Created API key '{name}' ({key_prefix}...)",
            payload={"api_key_id": str(api_key.id), "scopes": scopes},
        )
        await self._session.commit()
        return api_key, raw_key

    async def revoke_api_key(self, api_key_id: uuid.UUID, *, workspace_id: uuid.UUID) -> ApiKey:
        api_key = await self._repo.get_api_key_by_id(api_key_id)
        if api_key is None or api_key.workspace_id != workspace_id:
            raise ApiKeyNotFound(str(api_key_id))
        await self._repo.revoke_api_key(api_key)
        await self._audit.record(
            event_type="identity.api_key_revoked",
            actor_type="user",
            organization_id=api_key.organization_id,
            summary=f"Revoked API key '{api_key.name}'",
            payload={"api_key_id": str(api_key.id)},
        )
        await self._session.commit()
        return api_key

    async def authenticate(self, raw_key: str) -> ApiKey | None:
        key_hash = security.hash_refresh_token(raw_key)
        api_key = await self._repo.get_api_key_by_hash(key_hash)
        if api_key is None or api_key.status != "active":
            return None
        await self._repo.touch_api_key_last_used(api_key)
        await self._session.commit()
        return api_key
