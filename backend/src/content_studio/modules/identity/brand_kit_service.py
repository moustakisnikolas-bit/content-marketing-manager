import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from content_studio.modules.governance.service import AuditService
from content_studio.modules.identity.exceptions import BrandProfileNotFound, BrandRuleNotFound
from content_studio.modules.identity.models import BrandProfile, BrandRule
from content_studio.modules.identity.repository import IdentityRepository


class BrandKitService:
    """Backs the Brand Kit page — a BrandProfile plus its BrandRule set.
    Enforcement already existed before this service (generation_service.py's
    quality gate reads BrandRule rows directly); this is the missing other
    half — creating and editing them in the first place."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self._repo = IdentityRepository(session)
        self._audit = AuditService(session)

    async def create_profile(
        self,
        *,
        organization_id: uuid.UUID,
        workspace_id: uuid.UUID,
        user_id: uuid.UUID,
        name: str,
        tone_description: str | None,
        product_line_description: str | None,
        vocabulary: list[str],
        colors: list[str],
        target_audiences: list[str],
        default_ctas: list[str],
        brand_pillars_description: str | None = None,
    ) -> BrandProfile:
        profile = await self._repo.create_brand_profile(
            workspace_id=workspace_id, name=name, tone_description=tone_description,
            product_line_description=product_line_description, brand_pillars_description=brand_pillars_description,
            vocabulary=vocabulary, colors=colors, target_audiences=target_audiences, default_ctas=default_ctas,
        )
        await self._audit.record(
            event_type="identity.brand_profile_created",
            actor_type="user",
            actor_id=str(user_id),
            organization_id=organization_id,
            summary=f"Created brand profile '{name}'",
            payload={"brand_profile_id": str(profile.id)},
        )
        await self._session.commit()
        return profile

    async def update_profile(
        self,
        profile_id: uuid.UUID,
        *,
        workspace_id: uuid.UUID,
        name: str,
        tone_description: str | None,
        product_line_description: str | None,
        vocabulary: list[str],
        colors: list[str],
        target_audiences: list[str],
        default_ctas: list[str],
        is_active: bool,
        brand_pillars_description: str | None = None,
    ) -> BrandProfile:
        profile = await self._get_workspace_profile(profile_id, workspace_id)
        await self._repo.update_brand_profile(
            profile, name=name, tone_description=tone_description, product_line_description=product_line_description,
            brand_pillars_description=brand_pillars_description,
            vocabulary=vocabulary, colors=colors, target_audiences=target_audiences, default_ctas=default_ctas,
            is_active=is_active,
        )
        await self._session.commit()
        return profile

    async def add_rule(
        self, profile_id: uuid.UUID, *, workspace_id: uuid.UUID, rule_type: str, description: str, is_blocking: bool
    ) -> BrandRule:
        profile = await self._get_workspace_profile(profile_id, workspace_id)
        rule = await self._repo.create_brand_rule(
            brand_profile_id=profile.id, rule_type=rule_type, description=description, is_blocking=is_blocking,
        )
        await self._session.commit()
        return rule

    async def remove_rule(self, rule_id: uuid.UUID, *, workspace_id: uuid.UUID) -> None:
        rule = await self._repo.get_brand_rule_by_id(rule_id)
        if rule is None:
            raise BrandRuleNotFound(str(rule_id))
        profile = await self._get_workspace_profile(rule.brand_profile_id, workspace_id)
        assert profile.id == rule.brand_profile_id
        await self._repo.delete_brand_rule(rule)
        await self._session.commit()

    async def _get_workspace_profile(self, profile_id: uuid.UUID, workspace_id: uuid.UUID) -> BrandProfile:
        profile = await self._repo.get_brand_profile_by_id(profile_id)
        if profile is None or profile.workspace_id != workspace_id:
            raise BrandProfileNotFound(str(profile_id))
        return profile
