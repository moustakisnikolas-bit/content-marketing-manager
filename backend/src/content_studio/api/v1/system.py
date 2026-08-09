import uuid

from fastapi import APIRouter
from pydantic import BaseModel

from content_studio.config import get_settings
from content_studio.workflows.client import get_temporal_client
from content_studio.workflows.ping import PingWorkflow

router = APIRouter(prefix="/system", tags=["system"])


class PingWorkflowResult(BaseModel):
    audit_event_id: str


@router.post("/temporal-ping", response_model=PingWorkflowResult)
async def trigger_temporal_ping() -> PingWorkflowResult:
    """Proves the Temporal integration end to end: starts a workflow, the
    worker executes its Activity, the Activity writes a real AuditEvent row
    via the Application Service layer, and we read the result back."""
    settings = get_settings()
    client = await get_temporal_client()
    result = await client.execute_workflow(
        PingWorkflow.run,
        "phase-1 temporal integration check",
        id=f"ping-{uuid.uuid4()}",
        task_queue=settings.temporal_task_queue,
    )
    return PingWorkflowResult(audit_event_id=result)
