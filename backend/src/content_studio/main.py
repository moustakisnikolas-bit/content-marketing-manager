from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from content_studio.api.middleware import RequestIDMiddleware
from content_studio.api.v1.router import api_v1_router
from content_studio.config import get_settings
from content_studio.db.seed import (
    ensure_default_agents,
    ensure_default_content_recipes,
    ensure_default_marketing_goals,
    ensure_default_metric_definitions,
    ensure_default_plans,
    ensure_default_strategy_version,
    ensure_default_tools,
)
from content_studio.db.session import SessionLocal
from content_studio.observability import configure_observability


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    async with SessionLocal() as session:
        await ensure_default_plans(session)
        await ensure_default_content_recipes(session)
        await ensure_default_marketing_goals(session)
        await ensure_default_metric_definitions(session)
        await ensure_default_strategy_version(session)
        await ensure_default_agents(session)
        await ensure_default_tools(session)
    yield


app = FastAPI(title="AI Content Studio Backend", version="0.1.0", lifespan=lifespan)
app.add_middleware(RequestIDMiddleware)
app.include_router(api_v1_router)
configure_observability(app, get_settings())


@app.get("/health", tags=["system"])
async def health() -> dict[str, str]:
    return {"status": "ok"}
