from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from content_studio.api.deps import ApiKeyContext, get_api_key_context, get_db_session
from content_studio.modules.analytics.repository import AnalyticsRepository
from content_studio.modules.analytics.schemas import RecommendationOut
from content_studio.modules.commerce.repository import CommerceRepository
from content_studio.modules.commerce.schemas import ProductOut

router = APIRouter(prefix="/public", tags=["public-api"])

# The public API's whole reason to exist: a rate-limited, API-key-authed,
# read-only window onto a workspace's own data — for an agency's client
# reporting integrations or a customer's own tooling. It reuses the exact
# same repositories every internal endpoint does; no parallel read path,
# no duplicated business logic.


def _require_scope(context: ApiKeyContext, scope: str) -> None:
    if scope not in context.scopes:
        raise HTTPException(status.HTTP_403_FORBIDDEN, f"This API key is missing the '{scope}' scope")


@router.get("/recommendations", response_model=list[RecommendationOut])
async def list_recommendations(
    context: ApiKeyContext = Depends(get_api_key_context), session: AsyncSession = Depends(get_db_session)
) -> list[RecommendationOut]:
    _require_scope(context, "analytics:read")
    repo = AnalyticsRepository(session)
    recommendations = await repo.list_recommendations_for_workspace(context.workspace_id)
    return [RecommendationOut.model_validate(r) for r in recommendations]


@router.get("/products", response_model=list[ProductOut])
async def list_products(
    context: ApiKeyContext = Depends(get_api_key_context), session: AsyncSession = Depends(get_db_session)
) -> list[ProductOut]:
    _require_scope(context, "commerce:read")
    repo = CommerceRepository(session)
    products = await repo.list_products_for_workspace(context.workspace_id)
    return [ProductOut.model_validate(p) for p in products]
