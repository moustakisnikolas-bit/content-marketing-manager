import asyncio
import logging
import sys

from temporalio.worker import Worker

import content_studio.db.models_registry  # noqa: F401  (populates Base.metadata for cross-module FKs)
from content_studio.config import get_settings
from content_studio.workflows.autopilot import (
    AutoPilotCampaignWorkflow,
    mark_item_cancelled_activity,
    run_autopilot_item_activity,
)
from content_studio.workflows.client import get_temporal_client
from content_studio.workflows.generation import (
    GenerationWorkflow,
    dispatch_generation,
    finalize_approved_activity,
    finalize_rejected_activity,
    reserve_generation_cost,
    run_quality_gate_activity,
)
from content_studio.workflows.ping import PingWorkflow, write_ping_audit_event
from content_studio.workflows.publication import (
    PublicationWorkflow,
    check_capability_activity,
    dispatch_publish_activity,
    finalize_rejected_publication_activity,
    mark_approved_activity,
    reconcile_activity,
)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


async def run_worker() -> None:
    settings = get_settings()
    client = await get_temporal_client()
    worker = Worker(
        client,
        task_queue=settings.temporal_task_queue,
        workflows=[PingWorkflow, GenerationWorkflow, PublicationWorkflow, AutoPilotCampaignWorkflow],
        activities=[
            write_ping_audit_event,
            reserve_generation_cost,
            dispatch_generation,
            run_quality_gate_activity,
            finalize_approved_activity,
            finalize_rejected_activity,
            check_capability_activity,
            dispatch_publish_activity,
            reconcile_activity,
            finalize_rejected_publication_activity,
            mark_approved_activity,
            run_autopilot_item_activity,
            mark_item_cancelled_activity,
        ],
    )
    logger.info("Temporal worker starting on task queue %s", settings.temporal_task_queue)
    await worker.run()


if __name__ == "__main__":
    if sys.platform == "win32":
        # asyncpg's SSL/socket connect has a known compatibility issue with
        # Windows' default ProactorEventLoop — connections hang and are
        # then cancelled mid-handshake. FastAPI's own event loop doesn't
        # hit this (uvicorn picks Selector on Windows), but a bare
        # asyncio.run() here defaults to Proactor, which is exactly what
        # broke the ping activity's DB connection.
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    asyncio.run(run_worker())
