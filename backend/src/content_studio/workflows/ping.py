from datetime import timedelta

from temporalio import activity, workflow
from temporalio.common import RetryPolicy

# Phase 1 scope: this workflow exists purely to prove the pattern end to
# end — Temporal server reachable, a worker executing an Activity, and that
# Activity calling into an Application Service (AuditService), matching the
# mandated dependency direction `Worker/Temporal Activity -> Application
# Service`. The real generation-lifecycle workflow (reserve -> dispatch ->
# quality gate -> review -> settle) arrives in Phase 2.


@activity.defn
async def write_ping_audit_event(message: str) -> str:
    # Imported inside the activity, not at module top level: activities run
    # in a worker process, which must not require importing Temporal's own
    # workflow sandbox restrictions into unrelated application modules.
    from content_studio.db.session import SessionLocal
    from content_studio.modules.governance.service import AuditService

    async with SessionLocal() as session:
        audit = AuditService(session)
        event = await audit.record(
            event_type="system.temporal_ping",
            actor_type="service",
            summary=message,
        )
        await session.commit()
        return str(event.id)


@workflow.defn
class PingWorkflow:
    @workflow.run
    async def run(self, message: str) -> str:
        return await workflow.execute_activity(
            write_ping_audit_event,
            message,
            start_to_close_timeout=timedelta(seconds=30),
            # No retries for this proof-of-pattern workflow: a failure
            # should surface immediately rather than being masked by
            # Temporal's default (near-unbounded) retry backoff. Real
            # business workflows from Phase 2 onward choose retry policies
            # deliberately per activity, not by relying on this default.
            retry_policy=RetryPolicy(maximum_attempts=1),
        )
