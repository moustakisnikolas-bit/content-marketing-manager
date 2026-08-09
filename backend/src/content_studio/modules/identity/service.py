import re
import secrets
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy.ext.asyncio import AsyncSession

from content_studio.modules.identity import security
from content_studio.modules.identity.exceptions import (
    EmailAlreadyRegistered,
    InvalidCredentials,
    InvalidRefreshToken,
    InvitationNotFound,
    InvitationNotPending,
    RoleNotFound,
    UserNotFound,
    WorkspaceNotFound,
)
from content_studio.modules.identity.models import (
    SYSTEM_ROLES,
    Invitation,
    Membership,
    Organization,
    Role,
    User,
    Workspace,
)
from content_studio.modules.identity.repository import IdentityRepository

OWNER_ROLE_NAME = "Owner"
INVITATION_TTL_DAYS = 14


def _slugify(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
    return f"{slug or 'org'}-{secrets.token_hex(3)}"


@dataclass(frozen=True)
class TokenPair:
    access_token: str
    refresh_token: str


@dataclass(frozen=True)
class SignupResult:
    user: User
    organization: Organization
    workspace: Workspace
    tokens: TokenPair


class IdentityService:
    """Application Service for signup/login/membership. Never touches the
    session directly — everything goes through IdentityRepository."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self._repo = IdentityRepository(session)

    async def signup(
        self, *, email: str, password: str, display_name: str, organization_name: str
    ) -> SignupResult:
        existing = await self._repo.get_user_by_email(email)
        if existing is not None:
            raise EmailAlreadyRegistered(email)

        user = await self._repo.create_user(
            email=email,
            hashed_password=security.hash_password(password),
            display_name=display_name,
        )
        organization = await self._repo.create_organization(
            name=organization_name, slug=_slugify(organization_name)
        )
        workspace = await self._repo.create_workspace(
            organization_id=organization.id, name="Default", slug="default"
        )
        # Seed the full role catalog up front (not just Owner) so Admin/
        # Editor/Client Viewer are immediately assignable when inviting
        # teammates or agency clients — see SYSTEM_ROLES.
        owner_role = None
        for role_name, permissions in SYSTEM_ROLES.items():
            role = await self._repo.create_role(
                organization_id=organization.id, name=role_name, permissions=permissions, is_system_role=True,
            )
            if role_name == OWNER_ROLE_NAME:
                owner_role = role
        assert owner_role is not None
        await self._repo.create_membership(
            user_id=user.id, workspace_id=workspace.id, role_id=owner_role.id
        )

        tokens = await self._issue_tokens(user_id=user.id, organization_id=organization.id)
        await self._session.commit()
        return SignupResult(user=user, organization=organization, workspace=workspace, tokens=tokens)

    async def login(self, *, email: str, password: str) -> TokenPair:
        user = await self._repo.get_user_by_email(email)
        if user is None or not security.verify_password(password, user.hashed_password):
            raise InvalidCredentials(email)
        if not user.is_active:
            raise InvalidCredentials(email)

        memberships = await self._repo.get_memberships_for_user(user.id)
        organization_id = await self._organization_id_for_membership(memberships[0]) if memberships else None

        tokens = await self._issue_tokens(user_id=user.id, organization_id=organization_id)
        await self._session.commit()
        return tokens

    async def refresh(self, *, raw_refresh_token: str) -> TokenPair:
        token_hash = security.hash_refresh_token(raw_refresh_token)
        stored = await self._repo.get_refresh_token(token_hash)
        now = datetime.now(UTC)
        if stored is None or stored.revoked_at is not None or stored.expires_at < now:
            raise InvalidRefreshToken

        await self._repo.revoke_refresh_token(stored, revoked_at=now)

        memberships = await self._repo.get_memberships_for_user(stored.user_id)
        organization_id = await self._organization_id_for_membership(memberships[0]) if memberships else None

        tokens = await self._issue_tokens(user_id=stored.user_id, organization_id=organization_id)
        await self._session.commit()
        return tokens

    async def add_member(
        self, *, workspace_id: uuid.UUID, invitee_email: str, role_name: str
    ) -> Membership:
        """Direct add for a user who already has an account and doesn't
        need an invitation round-trip (e.g. test/seed setup, or an admin
        adding a known colleague). The Invitation flow below
        (invite_to_workspace/accept_invitation) is the real Phase 8
        onboarding path — it works whether or not the invitee has an
        account yet, and requires their explicit acceptance rather than
        binding a Membership unilaterally."""
        invitee = await self._repo.get_user_by_email(invitee_email)
        if invitee is None:
            raise UserNotFound(invitee_email)

        workspace = await self._repo.get_workspace_by_id(workspace_id)
        if workspace is None:
            raise WorkspaceNotFound(str(workspace_id))

        role = await self._repo.get_role_by_name(organization_id=workspace.organization_id, name=role_name)
        if role is None:
            raise RoleNotFound(role_name)

        membership = await self._repo.create_membership(
            user_id=invitee.id, workspace_id=workspace_id, role_id=role.id
        )
        await self._session.commit()
        return membership

    async def create_workspace(self, *, organization_id: uuid.UUID, name: str, owner_user_id: uuid.UUID) -> Workspace:
        """A new client/brand workspace within an existing organization —
        the concrete 'agency manages multiple client workspaces' primitive
        this phase adds. No new tenancy type: same Organization/Workspace/
        Membership/Role shape every other module already respects."""
        slug = _slugify(name)
        workspace = await self._repo.create_workspace(organization_id=organization_id, name=name, slug=slug)
        owner_role = await self._repo.get_role_by_name(organization_id=organization_id, name=OWNER_ROLE_NAME)
        assert owner_role is not None, "every organization is seeded with the full SYSTEM_ROLES catalog at signup"
        await self._repo.create_membership(user_id=owner_user_id, workspace_id=workspace.id, role_id=owner_role.id)
        await self._session.commit()
        return workspace

    async def list_workspaces_for_user(self, user_id: uuid.UUID) -> list[tuple[Workspace, Role]]:
        memberships = await self._repo.get_memberships_for_user(user_id)
        results: list[tuple[Workspace, Role]] = []
        for membership in memberships:
            workspace = await self._repo.get_workspace_by_id(membership.workspace_id)
            role = await self._repo.get_role_by_id(membership.role_id)
            assert workspace is not None and role is not None
            results.append((workspace, role))
        return results

    async def invite_to_workspace(
        self, *, workspace_id: uuid.UUID, email: str, role_name: str, invited_by_user_id: uuid.UUID
    ) -> tuple[Invitation, str]:
        workspace = await self._repo.get_workspace_by_id(workspace_id)
        if workspace is None:
            raise WorkspaceNotFound(str(workspace_id))
        role = await self._repo.get_role_by_name(organization_id=workspace.organization_id, name=role_name)
        if role is None:
            raise RoleNotFound(role_name)

        raw_token, token_hash, _ = security.generate_opaque_token(prefix="inv")
        invitation = await self._repo.create_invitation(
            organization_id=workspace.organization_id, workspace_id=workspace_id, email=email, role_id=role.id,
            invited_by_user_id=invited_by_user_id,
            token_hash=token_hash, expires_at=datetime.now(UTC) + timedelta(days=INVITATION_TTL_DAYS),
        )
        await self._session.commit()
        return invitation, raw_token

    async def accept_invitation(self, *, raw_token: str, accepting_user: User) -> Membership:
        token_hash = security.hash_refresh_token(raw_token)
        invitation = await self._repo.get_invitation_by_token_hash(token_hash)
        now = datetime.now(UTC)
        if invitation is None:
            raise InvitationNotFound(raw_token)
        if invitation.status != "pending" or invitation.expires_at < now:
            raise InvitationNotPending(str(invitation.id))
        if invitation.email.lower() != accepting_user.email.lower():
            # Never bind a Membership to whoever happens to hold the link —
            # only the invited address can accept it.
            raise InvitationNotFound(raw_token)

        membership = await self._repo.create_membership(
            user_id=accepting_user.id, workspace_id=invitation.workspace_id, role_id=invitation.role_id,
        )
        await self._repo.mark_invitation_accepted(invitation)
        await self._session.commit()
        return membership

    async def update_organization_branding(
        self,
        *,
        organization_id: uuid.UUID,
        product_name: str | None,
        logo_url: str | None,
        primary_color: str | None,
    ) -> Organization:
        organization = await self._repo.get_organization_by_id(organization_id)
        if organization is None:
            raise WorkspaceNotFound(str(organization_id))
        await self._repo.update_organization_branding(
            organization, product_name=product_name, logo_url=logo_url, primary_color=primary_color,
        )
        await self._session.commit()
        return organization

    async def _organization_id_for_membership(self, membership: Membership) -> uuid.UUID:
        workspace = await self._session.get(Workspace, membership.workspace_id)
        assert workspace is not None
        return workspace.organization_id

    async def _issue_tokens(
        self, *, user_id: uuid.UUID, organization_id: uuid.UUID | None
    ) -> TokenPair:
        access_token = security.create_access_token(user_id, organization_id)
        raw_refresh, refresh_hash, expires_at = security.generate_refresh_token()
        await self._repo.store_refresh_token(
            user_id=user_id, token_hash=refresh_hash, expires_at=expires_at
        )
        return TokenPair(access_token=access_token, refresh_token=raw_refresh)
