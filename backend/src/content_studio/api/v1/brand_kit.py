import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from content_studio.api.deps import (
    WorkspaceContext,
    get_current_user,
    get_db_session,
    get_workspace_context,
)
from content_studio.modules.identity.brand_kit_service import BrandKitService
from content_studio.modules.identity.exceptions import BrandProfileNotFound, BrandRuleNotFound
from content_studio.modules.identity.models import User
from content_studio.modules.identity.repository import IdentityRepository
from content_studio.modules.identity.schemas import (
    BrandProfileDetailOut,
    BrandProfileOut,
    BrandRuleOut,
    CreateBrandProfileRequest,
    CreateBrandRuleRequest,
    UpdateBrandProfileRequest,
)

router = APIRouter(prefix="/brand-profiles", tags=["brand-kit"])


async def _detail(repo: IdentityRepository, profile) -> BrandProfileDetailOut:
    rules = await repo.list_rules_for_profile(profile.id)
    return BrandProfileDetailOut(
        profile=BrandProfileOut.model_validate(profile), rules=[BrandRuleOut.model_validate(r) for r in rules]
    )


@router.get("", response_model=list[BrandProfileOut])
async def list_brand_profiles(
    context: WorkspaceContext = Depends(get_workspace_context), session: AsyncSession = Depends(get_db_session)
) -> list[BrandProfileOut]:
    repo = IdentityRepository(session)
    profiles = await repo.list_brand_profiles_for_workspace(context.workspace_id)
    return [BrandProfileOut.model_validate(p) for p in profiles]


@router.post("", response_model=BrandProfileOut, status_code=status.HTTP_201_CREATED)
async def create_brand_profile(
    body: CreateBrandProfileRequest,
    current_user: User = Depends(get_current_user),
    context: WorkspaceContext = Depends(get_workspace_context),
    session: AsyncSession = Depends(get_db_session),
) -> BrandProfileOut:
    service = BrandKitService(session)
    profile = await service.create_profile(
        organization_id=context.organization_id, workspace_id=context.workspace_id, user_id=current_user.id,
        name=body.name, tone_description=body.tone_description, product_line_description=body.product_line_description,
        vocabulary=body.vocabulary, colors=body.colors,
        target_audiences=body.target_audiences, default_ctas=body.default_ctas,
    )
    return BrandProfileOut.model_validate(profile)


@router.get("/{profile_id}", response_model=BrandProfileDetailOut)
async def get_brand_profile(
    profile_id: uuid.UUID,
    context: WorkspaceContext = Depends(get_workspace_context),
    session: AsyncSession = Depends(get_db_session),
) -> BrandProfileDetailOut:
    repo = IdentityRepository(session)
    profile = await repo.get_brand_profile_by_id(profile_id)
    if profile is None or profile.workspace_id != context.workspace_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Brand profile not found")
    return await _detail(repo, profile)


@router.put("/{profile_id}", response_model=BrandProfileOut)
async def update_brand_profile(
    profile_id: uuid.UUID,
    body: UpdateBrandProfileRequest,
    context: WorkspaceContext = Depends(get_workspace_context),
    session: AsyncSession = Depends(get_db_session),
) -> BrandProfileOut:
    service = BrandKitService(session)
    try:
        profile = await service.update_profile(
            profile_id, workspace_id=context.workspace_id, name=body.name, tone_description=body.tone_description,
            product_line_description=body.product_line_description,
            vocabulary=body.vocabulary, colors=body.colors, target_audiences=body.target_audiences,
            default_ctas=body.default_ctas, is_active=body.is_active,
        )
    except BrandProfileNotFound as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Brand profile not found") from exc
    return BrandProfileOut.model_validate(profile)


@router.post("/{profile_id}/rules", response_model=BrandRuleOut, status_code=status.HTTP_201_CREATED)
async def add_brand_rule(
    profile_id: uuid.UUID,
    body: CreateBrandRuleRequest,
    context: WorkspaceContext = Depends(get_workspace_context),
    session: AsyncSession = Depends(get_db_session),
) -> BrandRuleOut:
    service = BrandKitService(session)
    try:
        rule = await service.add_rule(
            profile_id, workspace_id=context.workspace_id, rule_type=body.rule_type, description=body.description,
            is_blocking=body.is_blocking,
        )
    except BrandProfileNotFound as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Brand profile not found") from exc
    return BrandRuleOut.model_validate(rule)


@router.delete("/rules/{rule_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_brand_rule(
    rule_id: uuid.UUID,
    context: WorkspaceContext = Depends(get_workspace_context),
    session: AsyncSession = Depends(get_db_session),
) -> None:
    service = BrandKitService(session)
    try:
        await service.remove_rule(rule_id, workspace_id=context.workspace_id)
    except BrandRuleNotFound as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Brand rule not found") from exc
    except BrandProfileNotFound as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Brand rule not found") from exc
