import uuid
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from content_studio.modules.identity.models import (
    ApiKey,
    BrandProfile,
    BrandRule,
    Invitation,
    Membership,
    Organization,
    RefreshToken,
    Role,
    User,
    Workspace,
)


class IdentityRepository:
    """Owns all direct ORM access for the identity module. Application
    Services depend on this, never on the SQLAlchemy session directly, per
    the mandated API -> Service -> Repository -> PostgreSQL dependency
    direction."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_user_by_email(self, email: str) -> User | None:
        result = await self._session.execute(select(User).where(User.email == email))
        return result.scalar_one_or_none()

    async def get_user_by_id(self, user_id: uuid.UUID) -> User | None:
        result = await self._session.execute(select(User).where(User.id == user_id))
        return result.scalar_one_or_none()

    async def create_user(self, *, email: str, hashed_password: str, display_name: str) -> User:
        user = User(email=email, hashed_password=hashed_password, display_name=display_name)
        self._session.add(user)
        await self._session.flush()
        return user

    async def create_organization(self, *, name: str, slug: str) -> Organization:
        org = Organization(name=name, slug=slug)
        self._session.add(org)
        await self._session.flush()
        return org

    async def create_workspace(
        self, *, organization_id: uuid.UUID, name: str, slug: str
    ) -> Workspace:
        workspace = Workspace(organization_id=organization_id, name=name, slug=slug)
        self._session.add(workspace)
        await self._session.flush()
        return workspace

    async def create_role(
        self, *, organization_id: uuid.UUID, name: str, permissions: list[str], is_system_role: bool = False
    ) -> Role:
        role = Role(
            organization_id=organization_id,
            name=name,
            permissions=permissions,
            is_system_role=is_system_role,
        )
        self._session.add(role)
        await self._session.flush()
        return role

    async def create_membership(
        self, *, user_id: uuid.UUID, workspace_id: uuid.UUID, role_id: uuid.UUID
    ) -> Membership:
        membership = Membership(user_id=user_id, workspace_id=workspace_id, role_id=role_id)
        self._session.add(membership)
        await self._session.flush()
        return membership

    async def get_memberships_for_user(self, user_id: uuid.UUID) -> list[Membership]:
        result = await self._session.execute(
            select(Membership).where(Membership.user_id == user_id)
        )
        return list(result.scalars().all())

    async def store_refresh_token(
        self, *, user_id: uuid.UUID, token_hash: str, expires_at: datetime
    ) -> RefreshToken:
        token = RefreshToken(user_id=user_id, token_hash=token_hash, expires_at=expires_at)
        self._session.add(token)
        await self._session.flush()
        return token

    async def get_refresh_token(self, token_hash: str) -> RefreshToken | None:
        result = await self._session.execute(
            select(RefreshToken).where(RefreshToken.token_hash == token_hash)
        )
        return result.scalar_one_or_none()

    async def revoke_refresh_token(self, token: RefreshToken, *, revoked_at: datetime) -> None:
        token.revoked_at = revoked_at
        await self._session.flush()

    # -- Organizations / workspaces --------------------------------------------

    async def get_organization_by_id(self, organization_id: uuid.UUID) -> Organization | None:
        return await self._session.get(Organization, organization_id)

    async def get_workspace_by_id(self, workspace_id: uuid.UUID) -> Workspace | None:
        return await self._session.get(Workspace, workspace_id)

    async def list_workspaces_for_organization(self, organization_id: uuid.UUID) -> list[Workspace]:
        result = await self._session.execute(
            select(Workspace).where(Workspace.organization_id == organization_id).order_by(Workspace.name)
        )
        return list(result.scalars().all())

    async def get_role_by_id(self, role_id: uuid.UUID) -> Role | None:
        return await self._session.get(Role, role_id)

    async def get_role_by_name(self, *, organization_id: uuid.UUID, name: str) -> Role | None:
        result = await self._session.execute(
            select(Role).where(Role.organization_id == organization_id, Role.name == name)
        )
        return result.scalar_one_or_none()

    async def list_roles_for_organization(self, organization_id: uuid.UUID) -> list[Role]:
        result = await self._session.execute(select(Role).where(Role.organization_id == organization_id))
        return list(result.scalars().all())

    async def get_membership(self, *, user_id: uuid.UUID, workspace_id: uuid.UUID) -> Membership | None:
        result = await self._session.execute(
            select(Membership).where(Membership.user_id == user_id, Membership.workspace_id == workspace_id)
        )
        return result.scalar_one_or_none()

    async def list_memberships_for_workspace(self, workspace_id: uuid.UUID) -> list[Membership]:
        result = await self._session.execute(select(Membership).where(Membership.workspace_id == workspace_id))
        return list(result.scalars().all())

    # -- Invitations ---------------------------------------------------------

    async def create_invitation(
        self,
        *,
        organization_id: uuid.UUID,
        workspace_id: uuid.UUID,
        email: str,
        role_id: uuid.UUID,
        invited_by_user_id: uuid.UUID,
        token_hash: str,
        expires_at: datetime,
    ) -> Invitation:
        invitation = Invitation(
            organization_id=organization_id, workspace_id=workspace_id, email=email, role_id=role_id,
            invited_by_user_id=invited_by_user_id, token_hash=token_hash, expires_at=expires_at,
        )
        self._session.add(invitation)
        await self._session.flush()
        return invitation

    async def get_invitation_by_token_hash(self, token_hash: str) -> Invitation | None:
        result = await self._session.execute(select(Invitation).where(Invitation.token_hash == token_hash))
        return result.scalar_one_or_none()

    async def get_invitation_by_id(self, invitation_id: uuid.UUID) -> Invitation | None:
        return await self._session.get(Invitation, invitation_id)

    async def list_pending_invitations_for_workspace(self, workspace_id: uuid.UUID) -> list[Invitation]:
        result = await self._session.execute(
            select(Invitation).where(Invitation.workspace_id == workspace_id, Invitation.status == "pending")
        )
        return list(result.scalars().all())

    async def mark_invitation_accepted(self, invitation: Invitation) -> None:
        invitation.status = "accepted"
        invitation.accepted_at = datetime.now(UTC)
        await self._session.flush()

    async def revoke_invitation(self, invitation: Invitation) -> None:
        invitation.status = "revoked"
        await self._session.flush()

    # -- API keys ---------------------------------------------------------

    async def create_api_key(
        self,
        *,
        organization_id: uuid.UUID,
        workspace_id: uuid.UUID,
        created_by_user_id: uuid.UUID,
        name: str,
        key_prefix: str,
        key_hash: str,
        scopes: list[str],
    ) -> ApiKey:
        api_key = ApiKey(
            organization_id=organization_id, workspace_id=workspace_id, created_by_user_id=created_by_user_id,
            name=name, key_prefix=key_prefix, key_hash=key_hash, scopes=scopes,
        )
        self._session.add(api_key)
        await self._session.flush()
        return api_key

    async def get_api_key_by_hash(self, key_hash: str) -> ApiKey | None:
        result = await self._session.execute(select(ApiKey).where(ApiKey.key_hash == key_hash))
        return result.scalar_one_or_none()

    async def get_api_key_by_id(self, api_key_id: uuid.UUID) -> ApiKey | None:
        return await self._session.get(ApiKey, api_key_id)

    async def list_api_keys_for_workspace(self, workspace_id: uuid.UUID) -> list[ApiKey]:
        result = await self._session.execute(
            select(ApiKey).where(ApiKey.workspace_id == workspace_id).order_by(ApiKey.created_at.desc())
        )
        return list(result.scalars().all())

    async def touch_api_key_last_used(self, api_key: ApiKey) -> None:
        api_key.last_used_at = datetime.now(UTC)
        await self._session.flush()

    async def revoke_api_key(self, api_key: ApiKey) -> None:
        api_key.status = "revoked"
        api_key.revoked_at = datetime.now(UTC)
        await self._session.flush()

    async def update_organization_branding(
        self,
        organization: Organization,
        *,
        product_name: str | None,
        logo_url: str | None,
        primary_color: str | None,
    ) -> None:
        organization.branding_product_name = product_name
        organization.branding_logo_url = logo_url
        organization.branding_primary_color = primary_color
        await self._session.flush()

    # -- Brand kit ---------------------------------------------------

    async def create_brand_profile(
        self,
        *,
        workspace_id: uuid.UUID,
        name: str,
        tone_description: str | None,
        product_line_description: str | None,
        vocabulary: list[str],
        colors: list[str],
        target_audiences: list[str],
        default_ctas: list[str],
    ) -> BrandProfile:
        profile = BrandProfile(
            workspace_id=workspace_id, name=name, tone_description=tone_description,
            product_line_description=product_line_description, vocabulary=vocabulary,
            colors=colors, target_audiences=target_audiences, default_ctas=default_ctas,
        )
        self._session.add(profile)
        await self._session.flush()
        return profile

    async def get_brand_profile_by_id(self, profile_id: uuid.UUID) -> BrandProfile | None:
        return await self._session.get(BrandProfile, profile_id)

    async def list_brand_profiles_for_workspace(self, workspace_id: uuid.UUID) -> list[BrandProfile]:
        result = await self._session.execute(
            select(BrandProfile).where(BrandProfile.workspace_id == workspace_id).order_by(BrandProfile.name)
        )
        return list(result.scalars().all())

    async def update_brand_profile(
        self,
        profile: BrandProfile,
        *,
        name: str,
        tone_description: str | None,
        product_line_description: str | None,
        vocabulary: list[str],
        colors: list[str],
        target_audiences: list[str],
        default_ctas: list[str],
        is_active: bool,
    ) -> None:
        profile.name = name
        profile.tone_description = tone_description
        profile.product_line_description = product_line_description
        profile.vocabulary = vocabulary
        profile.colors = colors
        profile.target_audiences = target_audiences
        profile.default_ctas = default_ctas
        profile.is_active = is_active
        await self._session.flush()

    async def create_brand_rule(
        self, *, brand_profile_id: uuid.UUID, rule_type: str, description: str, is_blocking: bool
    ) -> BrandRule:
        rule = BrandRule(
            brand_profile_id=brand_profile_id, rule_type=rule_type, description=description, is_blocking=is_blocking,
        )
        self._session.add(rule)
        await self._session.flush()
        return rule

    async def get_brand_rule_by_id(self, rule_id: uuid.UUID) -> BrandRule | None:
        return await self._session.get(BrandRule, rule_id)

    async def list_rules_for_profile(self, brand_profile_id: uuid.UUID) -> list[BrandRule]:
        result = await self._session.execute(
            select(BrandRule).where(BrandRule.brand_profile_id == brand_profile_id)
        )
        return list(result.scalars().all())

    async def delete_brand_rule(self, rule: BrandRule) -> None:
        await self._session.delete(rule)
        await self._session.flush()
