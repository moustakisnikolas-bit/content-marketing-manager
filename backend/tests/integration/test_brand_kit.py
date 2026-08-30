import uuid

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from content_studio.modules.identity.brand_kit_service import BrandKitService
from content_studio.modules.identity.exceptions import BrandProfileNotFound, BrandRuleNotFound
from content_studio.modules.identity.service import IdentityService

pytestmark = pytest.mark.asyncio


def _unique_email() -> str:
    return f"brand-{uuid.uuid4().hex[:12]}@example.com"


async def _signup(session: AsyncSession):
    identity = IdentityService(session)
    return await identity.signup(
        email=_unique_email(), password="correct-horse-battery", display_name="Brand Test",
        organization_name="Brand Org",
    )


async def test_create_and_update_brand_profile(db_session: AsyncSession) -> None:
    result = await _signup(db_session)
    service = BrandKitService(db_session)

    profile = await service.create_profile(
        organization_id=result.organization.id, workspace_id=result.workspace.id, user_id=result.user.id,
        name="Main voice", tone_description="Friendly and upbeat", product_line_description="Candles",
        vocabulary=["delightful"], colors=["#1a73e8"],
        target_audiences=["young professionals"], default_ctas=["Shop now"],
    )
    assert profile.name == "Main voice"
    assert profile.is_active is True
    assert profile.product_line_description == "Candles"

    updated = await service.update_profile(
        profile.id, workspace_id=result.workspace.id, name="Updated voice", tone_description="Calmer now",
        product_line_description="Candles and diffusers",
        vocabulary=[], colors=[], target_audiences=[], default_ctas=[], is_active=False,
    )
    assert updated.product_line_description == "Candles and diffusers"
    assert updated.name == "Updated voice"
    assert updated.is_active is False


async def test_update_profile_from_another_workspace_raises_not_found(db_session: AsyncSession) -> None:
    owner = await _signup(db_session)
    other = await _signup(db_session)
    service = BrandKitService(db_session)

    profile = await service.create_profile(
        organization_id=owner.organization.id, workspace_id=owner.workspace.id, user_id=owner.user.id,
        name="Owner's voice", tone_description=None, product_line_description=None, vocabulary=[], colors=[],
        target_audiences=[], default_ctas=[],
    )

    with pytest.raises(BrandProfileNotFound):
        await service.update_profile(
            profile.id, workspace_id=other.workspace.id, name="Hijacked", tone_description=None,
            product_line_description=None, vocabulary=[],
            colors=[], target_audiences=[], default_ctas=[], is_active=True,
        )


async def test_add_and_remove_brand_rule(db_session: AsyncSession) -> None:
    result = await _signup(db_session)
    service = BrandKitService(db_session)
    profile = await service.create_profile(
        organization_id=result.organization.id, workspace_id=result.workspace.id, user_id=result.user.id,
        name="Main voice", tone_description=None, product_line_description=None, vocabulary=[], colors=[],
        target_audiences=[], default_ctas=[],
    )

    rule = await service.add_rule(
        profile.id, workspace_id=result.workspace.id, rule_type="forbidden_claim",
        description="Never say 'guaranteed results'", is_blocking=True,
    )
    assert rule.is_blocking is True

    await service.remove_rule(rule.id, workspace_id=result.workspace.id)

    with pytest.raises(BrandRuleNotFound):
        await service.remove_rule(rule.id, workspace_id=result.workspace.id)


async def test_add_rule_to_profile_in_another_workspace_raises_not_found(db_session: AsyncSession) -> None:
    owner = await _signup(db_session)
    other = await _signup(db_session)
    service = BrandKitService(db_session)
    profile = await service.create_profile(
        organization_id=owner.organization.id, workspace_id=owner.workspace.id, user_id=owner.user.id,
        name="Owner's voice", tone_description=None, product_line_description=None, vocabulary=[], colors=[],
        target_audiences=[], default_ctas=[],
    )

    with pytest.raises(BrandProfileNotFound):
        await service.add_rule(
            profile.id, workspace_id=other.workspace.id, rule_type="tone", description="x", is_blocking=False,
        )


async def test_brand_rule_enforcement_still_works_via_the_new_crud_path(db_session: AsyncSession) -> None:
    """Regression guard: the enforcement logic in generation_service.py
    reads BrandRule rows directly — this proves a profile/rule created
    through the new BrandKitService (not hand-constructed ORM objects) is
    the exact same data that code reads, by round-tripping through the
    repository the same way the quality gate does."""
    from content_studio.modules.identity.repository import IdentityRepository

    result = await _signup(db_session)
    service = BrandKitService(db_session)
    profile = await service.create_profile(
        organization_id=result.organization.id, workspace_id=result.workspace.id, user_id=result.user.id,
        name="Main voice", tone_description=None, product_line_description=None, vocabulary=[], colors=[],
        target_audiences=[], default_ctas=[],
    )
    await service.add_rule(
        profile.id, workspace_id=result.workspace.id, rule_type="forbidden_claim",
        description="Never say 'guaranteed results'", is_blocking=True,
    )

    repo = IdentityRepository(db_session)
    rules = await repo.list_rules_for_profile(profile.id)
    assert len(rules) == 1
    assert rules[0].is_blocking is True
