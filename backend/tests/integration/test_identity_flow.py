import uuid

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from content_studio.modules.identity.exceptions import EmailAlreadyRegistered, InvalidCredentials
from content_studio.modules.identity.security import decode_access_token
from content_studio.modules.identity.service import OWNER_ROLE_NAME, IdentityService

pytestmark = pytest.mark.asyncio


def _unique_email() -> str:
    return f"user-{uuid.uuid4().hex[:12]}@example.com"


async def test_signup_creates_org_workspace_owner_role_and_membership(db_session: AsyncSession) -> None:
    service = IdentityService(db_session)
    email = _unique_email()

    result = await service.signup(
        email=email,
        password="correct-horse-battery",
        display_name="Test Founder",
        organization_name="Test Org",
    )

    assert result.user.email == email
    assert result.organization.name == "Test Org"
    assert result.workspace.organization_id == result.organization.id

    memberships = await service._repo.get_memberships_for_user(result.user.id)
    assert len(memberships) == 1
    assert memberships[0].workspace_id == result.workspace.id

    payload = decode_access_token(result.tokens.access_token)
    assert payload["sub"] == str(result.user.id)
    assert payload["org"] == str(result.organization.id)


async def test_signup_duplicate_email_raises(db_session: AsyncSession) -> None:
    service = IdentityService(db_session)
    email = _unique_email()

    await service.signup(
        email=email, password="correct-horse-battery", display_name="First", organization_name="Org A"
    )

    with pytest.raises(EmailAlreadyRegistered):
        await service.signup(
            email=email, password="another-password", display_name="Second", organization_name="Org B"
        )


async def test_login_succeeds_with_correct_password_and_fails_with_wrong(db_session: AsyncSession) -> None:
    service = IdentityService(db_session)
    email = _unique_email()
    await service.signup(
        email=email, password="correct-horse-battery", display_name="Login Test", organization_name="Login Org"
    )

    tokens = await service.login(email=email, password="correct-horse-battery")
    assert tokens.access_token
    assert tokens.refresh_token

    with pytest.raises(InvalidCredentials):
        await service.login(email=email, password="wrong-password")


async def test_refresh_token_is_single_use(db_session: AsyncSession) -> None:
    from content_studio.modules.identity.exceptions import InvalidRefreshToken

    service = IdentityService(db_session)
    email = _unique_email()
    signup_result = await service.signup(
        email=email, password="correct-horse-battery", display_name="Refresh Test", organization_name="Refresh Org"
    )
    raw_refresh = signup_result.tokens.refresh_token

    new_tokens = await service.refresh(raw_refresh_token=raw_refresh)
    # Not asserting access_token difference: JWT claims (sub/iat/exp/org)
    # have second-granularity timestamps, so two tokens issued within the
    # same wall-clock second are legitimately byte-identical — that's not
    # a bug. The actual single-use property under test is refresh-token
    # rotation, verified below by asserting the old refresh token is dead.
    assert new_tokens.refresh_token != raw_refresh
    decode_access_token(new_tokens.access_token)  # still a valid, decodable token

    with pytest.raises(InvalidRefreshToken):
        await service.refresh(raw_refresh_token=raw_refresh)


async def test_default_owner_role_has_wildcard_permissions(db_session: AsyncSession) -> None:
    service = IdentityService(db_session)
    email = _unique_email()
    result = await service.signup(
        email=email, password="correct-horse-battery", display_name="Role Test", organization_name="Role Org"
    )

    role = await service._repo.get_role_by_name(organization_id=result.organization.id, name=OWNER_ROLE_NAME)
    assert role is not None
    assert role.permissions == ["*"]
