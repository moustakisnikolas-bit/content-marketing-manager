import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from content_studio.api.middleware import get_request_id
from content_studio.correlation import (
    get_business_operation_id,
    get_correlation_id,
    get_tool_call_id,
    get_trace_id,
    get_workflow_id,
)
from content_studio.modules.governance.models import AuditEvent
from content_studio.modules.governance.repository import GovernanceRepository

# Application-layer enforcement only for now: no update()/delete() method is
# exposed. DB-level insert-only enforcement (REVOKE UPDATE/DELETE on this
# table for the app role) is a Phase 7 hardening step once the dedicated
# audit-writer DB role exists — see 26_IMPLEMENTATION_CHECKLIST.md.


class AuditService:
    def __init__(self, session: AsyncSession) -> None:
        self._repo = GovernanceRepository(session)

    async def record(
        self,
        *,
        event_type: str,
        actor_type: str,
        summary: str,
        organization_id: uuid.UUID | None = None,
        actor_id: str | None = None,
        payload: dict | None = None,
    ) -> AuditEvent:
        return await self._repo.add_event(
            organization_id=organization_id,
            event_type=event_type,
            actor_type=actor_type,
            actor_id=actor_id,
            summary=summary,
            payload=payload or {},
            request_id=get_request_id(),
            correlation_id=get_correlation_id(),
            trace_id=get_trace_id(),
            tool_call_id=get_tool_call_id(),
            workflow_id=get_workflow_id(),
            business_operation_id=get_business_operation_id(),
        )
