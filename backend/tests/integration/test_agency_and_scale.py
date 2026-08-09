import uuid

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from content_studio.config import get_settings
from content_studio.modules.identity.api_key_service import ApiKeyService
from content_studio.modules.identity.exceptions import InvitationNotFound, InvitationNotPending
from content_studio.modules.identity.models import SYSTEM_ROLES
from content_studio.modules.identity.permissions import has_permission
from content_studio.modules.identity.repository import IdentityRepository
from content_studio.modules.identity.service import IdentityService
from content_studio.rate_limit import RateLimiter, get_redis_client

pytestmark = pytest.mark.asyncio


def _unique_email() -> str:
    return f"user-{uuid.uuid4().hex[:12]}@example.com"


async def _signup(service: IdentityService, *, org_name: str = "Agency Org"):
    return await service.signup(
        email=_unique_email(), password="correct-horse-battery", display_name="Founder", organization_name=org_name,
    )


async def test_signup_seeds_full_role_catalog(db_session: AsyncSession) -> None:
    service = IdentityService(db_session)
    result = await _signup(service)

    repo = IdentityRepository(db_session)
    roles = await repo.list_roles_for_organization(result.organization.id)
    assert {r.name for r in roles} == set(SYSTEM_ROLES.keys())
    editor = next(r for r in roles if r.name == "Editor")
    assert "content:manage" in editor.permissions
    assert "*" not in editor.permissions


async def test_has_permission_wildcard_and_exact_match() -> None:
    assert has_permission(["*"], "billing:manage") is True
    assert has_permission(["content:manage"], "content:manage") is True
    assert has_permission(["content:manage"], "billing:manage") is False
    assert has_permission([], "content:manage") is False


async def test_agency_can_create_additional_client_workspace(db_session: AsyncSession) -> None:
    service = IdentityService(db_session)
    result = await _signup(service)

    second_workspace = await service.create_workspace(
        organization_id=result.organization.id, name="Client A", owner_user_id=result.user.id,
    )
    assert second_workspace.organization_id == result.organization.id
    assert second_workspace.slug != result.workspace.slug

    workspaces = await service.list_workspaces_for_user(result.user.id)
    assert {w.id for w, _ in workspaces} == {result.workspace.id, second_workspace.id}
    assert all(role.name == "Owner" for _, role in workspaces)


async def test_workspace_slugs_are_unique_within_an_organization(db_session: AsyncSession) -> None:
    service = IdentityService(db_session)
    result = await _signup(service)

    a = await service.create_workspace(organization_id=result.organization.id, name="Same Name", owner_user_id=result.user.id)
    b = await service.create_workspace(organization_id=result.organization.id, name="Same Name", owner_user_id=result.user.id)
    assert a.slug != b.slug


async def test_user_only_sees_memberships_they_actually_have(db_session: AsyncSession) -> None:
    """The tenant-isolation invariant get_workspace_context's X-Workspace-Id
    switching depends on: a user's membership list never includes a
    workspace from an organization they weren't added to — same isolation
    guarantee Phase 1 established, now load-bearing for workspace
    switching too."""
    service = IdentityService(db_session)
    org_a = await _signup(service, org_name="Org A")
    org_b = await _signup(service, org_name="Org B")

    repo = IdentityRepository(db_session)
    memberships_a = await repo.get_memberships_for_user(org_a.user.id)
    assert {m.workspace_id for m in memberships_a} == {org_a.workspace.id}
    assert org_b.workspace.id not in {m.workspace_id for m in memberships_a}


async def test_invite_and_accept_flow(db_session: AsyncSession) -> None:
    service = IdentityService(db_session)
    inviter = await _signup(service)
    invitee_email = _unique_email()
    invitee_signup = await service.signup(
        email=invitee_email, password="correct-horse-battery", display_name="Invitee", organization_name="Invitee's Own Org",
    )

    invitation, raw_token = await service.invite_to_workspace(
        workspace_id=inviter.workspace.id, email=invitee_email, role_name="Client Viewer",
        invited_by_user_id=inviter.user.id,
    )
    assert invitation.status == "pending"

    membership = await service.accept_invitation(raw_token=raw_token, accepting_user=invitee_signup.user)
    assert membership.workspace_id == inviter.workspace.id

    repo = IdentityRepository(db_session)
    role = await repo.get_role_by_id(membership.role_id)
    assert role is not None and role.name == "Client Viewer"

    updated_invitation = await repo.get_invitation_by_id(invitation.id)
    assert updated_invitation.status == "accepted"

    # Single-use: the same token cannot be accepted twice.
    with pytest.raises(InvitationNotPending):
        await service.accept_invitation(raw_token=raw_token, accepting_user=invitee_signup.user)


async def test_invitation_rejects_wrong_email(db_session: AsyncSession) -> None:
    service = IdentityService(db_session)
    inviter = await _signup(service)
    stranger = await _signup(service, org_name="Stranger Org")

    _, raw_token = await service.invite_to_workspace(
        workspace_id=inviter.workspace.id, email="someone-else@example.com", role_name="Editor",
        invited_by_user_id=inviter.user.id,
    )

    with pytest.raises(InvitationNotFound):
        await service.accept_invitation(raw_token=raw_token, accepting_user=stranger.user)


async def test_organization_branding_round_trip(db_session: AsyncSession) -> None:
    service = IdentityService(db_session)
    result = await _signup(service)

    updated = await service.update_organization_branding(
        organization_id=result.organization.id, product_name="Acme Studio", logo_url="https://cdn.test/logo.png",
        primary_color="#1a73e8",
    )
    assert updated.branding_product_name == "Acme Studio"
    assert updated.branding_primary_color == "#1a73e8"


async def test_api_key_authenticates_then_stops_working_after_revoke(db_session: AsyncSession) -> None:
    service = IdentityService(db_session)
    result = await _signup(service)
    api_key_service = ApiKeyService(db_session)

    api_key, raw_key = await api_key_service.create_api_key(
        organization_id=result.organization.id, workspace_id=result.workspace.id,
        created_by_user_id=result.user.id, name="Reporting integration", scopes=["analytics:read"],
    )
    assert raw_key.startswith("csk_")
    assert api_key.key_prefix in raw_key

    authenticated = await api_key_service.authenticate(raw_key)
    assert authenticated is not None
    assert authenticated.id == api_key.id

    await api_key_service.revoke_api_key(api_key.id, workspace_id=result.workspace.id)
    assert await api_key_service.authenticate(raw_key) is None


async def test_api_key_authenticate_rejects_garbage(db_session: AsyncSession) -> None:
    api_key_service = ApiKeyService(db_session)
    assert await api_key_service.authenticate("not-a-real-key") is None


async def test_rate_limiter_blocks_after_limit_via_real_redis() -> None:
    client = get_redis_client(get_settings().redis_url)
    limiter = RateLimiter(client)
    key = f"test-{uuid.uuid4().hex[:12]}"

    results = [await limiter.check_and_increment(key, limit=3, window_seconds=60) for _ in range(4)]

    assert [r.allowed for r in results] == [True, True, True, False]
    assert results[-1].remaining == 0
