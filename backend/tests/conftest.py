import os
import sys
from collections.abc import AsyncIterator
from pathlib import Path

import pytest
import pytest_asyncio
from alembic.config import Config
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from testcontainers.community.postgres import PostgresContainer

from alembic import command

BACKEND_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_ROOT / "src"))


@pytest.fixture(scope="session")
def postgres_container() -> AsyncIterator[PostgresContainer]:
    with PostgresContainer("postgres:16-alpine") as postgres:
        yield postgres


@pytest.fixture(scope="session")
def database_url(postgres_container: PostgresContainer) -> str:
    sync_url = postgres_container.get_connection_url()
    return sync_url.replace("postgresql+psycopg2", "postgresql+asyncpg")


@pytest.fixture(scope="session", autouse=True)
def _migrated_schema(database_url: str) -> None:
    """Runs the real Alembic migration chain against a fresh testcontainers
    Postgres — per the mandated 'PostgreSQL integration tests' rule, this
    never substitutes SQLite-in-memory."""
    os.environ["CS_DATABASE_URL"] = database_url

    # get_settings() is lru_cache'd; if anything imported during collection
    # already called it (pinning the pre-test-env default URL), clear that
    # here so env.py's own get_settings() call picks up the container URL.
    from content_studio.config import get_settings

    get_settings.cache_clear()

    alembic_cfg = Config(str(BACKEND_ROOT / "alembic.ini"))
    alembic_cfg.set_main_option("script_location", str(BACKEND_ROOT / "alembic"))
    command.upgrade(alembic_cfg, "head")


@pytest_asyncio.fixture
async def db_session(database_url: str, _migrated_schema: None) -> AsyncIterator[AsyncSession]:
    """A fresh engine per test function. Session-scoping the async engine
    across pytest-asyncio's per-test event loops causes asyncpg connections
    to bind to a closed loop after the first test — surfacing as spurious
    'relation does not exist' errors on every test after the first, since
    the pool silently reuses a connection tied to a dead loop instead of
    reconnecting to the (correctly migrated) database. A pooled engine is
    fine here (unlike the session-scoped version that caused the bug) since
    every connection this pool ever hands out is created and used within
    this one test function's single event loop, then the whole engine
    (and its pool) is disposed before the next test gets a fresh one."""
    engine: AsyncEngine = create_async_engine(database_url, pool_pre_ping=True)
    session_factory = async_sessionmaker(bind=engine, expire_on_commit=False, autoflush=False)
    async with session_factory() as session:
        yield session
        await session.rollback()
    await engine.dispose()
