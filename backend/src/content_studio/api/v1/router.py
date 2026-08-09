from fastapi import APIRouter

from content_studio.api.v1 import (
    analytics,
    api_keys,
    assets,
    auth,
    billing,
    brand_kit,
    commerce,
    content,
    governance,
    marketing,
    organizations,
    public,
    publishing,
    system,
)

api_v1_router = APIRouter(prefix="/api/v1")
api_v1_router.include_router(auth.router)
api_v1_router.include_router(billing.router)
api_v1_router.include_router(assets.router)
api_v1_router.include_router(brand_kit.router)
api_v1_router.include_router(content.router)
api_v1_router.include_router(publishing.router)
api_v1_router.include_router(marketing.router)
api_v1_router.include_router(analytics.router)
api_v1_router.include_router(commerce.router)
api_v1_router.include_router(governance.router)
api_v1_router.include_router(organizations.router)
api_v1_router.include_router(api_keys.router)
api_v1_router.include_router(public.router)
api_v1_router.include_router(system.router)
