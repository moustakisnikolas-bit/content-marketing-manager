import asyncio
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta

from temporalio import activity, workflow
from temporalio.common import RetryPolicy

# Phase 3's publication-lifecycle workflow — same shape as Phase 2's
# GenerationWorkflow (durable human-review wait via signal), extended with
# a durable scheduling sleep and a post-publish reconciliation step so a
# plan's status reflects what the platform actually reports, not just an
# optimistic local flag.


@dataclass
class PublicationWorkflowInput:
    plan_id: str
    # Threaded through from the HTTP request that started this workflow
    # (see api/v1/publishing.py) so every AuditEvent an activity writes
    # shares the same correlation_id as the request that triggered it —
    # activities run in a separate worker process, so this has to be
    # passed explicitly as workflow/activity input, not inherited via
    # contextvars. See correlation.py.
    correlation_id: str | None = None


@dataclass
class PublicationWorkflowResult:
    status: str
    reason: str | None = None


async def _build_publishing_service(platform: str):
    from content_studio.adapters.factory import get_secrets_adapter, get_social_platform_adapter
    from content_studio.adapters.object_storage.seaweedfs import SeaweedFSObjectStorage
    from content_studio.config import get_settings
    from content_studio.db.session import SessionLocal
    from content_studio.modules.publishing.service import PublishingService

    settings = get_settings()
    session = SessionLocal()
    service = PublishingService(
        session,
        platform_adapter=get_social_platform_adapter(settings, platform),
        secrets=get_secrets_adapter(settings),
        object_storage=SeaweedFSObjectStorage(settings),
    )
    return session, service


async def _platform_for_plan(plan_id: str) -> str:
    from content_studio.db.session import SessionLocal
    from content_studio.modules.publishing.repository import PublishingRepository

    async with SessionLocal() as session:
        repo = PublishingRepository(session)
        plan = await repo.get_publication_plan_by_id(uuid.UUID(plan_id))
        assert plan is not None
        connection = await repo.get_connection_by_id(plan.platform_connection_id)
        assert connection is not None
        return connection.platform


def _activity_correlation_scope(correlation_id: str | None):
    from content_studio.correlation import correlation_scope

    workflow_id = activity.info().workflow_id
    return correlation_scope(correlation_id=correlation_id, workflow_id=workflow_id)


@activity.defn
async def check_capability_activity(plan_id: str, correlation_id: str | None = None) -> dict:
    platform = await _platform_for_plan(plan_id)
    session, service = await _build_publishing_service(platform)
    async with session:
        with _activity_correlation_scope(correlation_id):
            result = await service.check_capability(uuid.UUID(plan_id))
        return {"ok": result.ok, "error": result.error}


@activity.defn
async def dispatch_publish_activity(plan_id: str, correlation_id: str | None = None) -> dict:
    platform = await _platform_for_plan(plan_id)
    session, service = await _build_publishing_service(platform)
    async with session:
        with _activity_correlation_scope(correlation_id):
            result = await service.dispatch_publish(uuid.UUID(plan_id))
        return {"ok": result.ok, "error": result.error, "attempt_id": result.attempt_id}


@activity.defn
async def reconcile_activity(plan_id: str, attempt_id: str, correlation_id: str | None = None) -> dict:
    platform = await _platform_for_plan(plan_id)
    session, service = await _build_publishing_service(platform)
    async with session:
        with _activity_correlation_scope(correlation_id):
            result = await service.reconcile(uuid.UUID(plan_id), uuid.UUID(attempt_id))
        return {"matches_expected": result.matches_expected, "external_status": result.external_status}


@activity.defn
async def finalize_rejected_publication_activity(
    plan_id: str, reviewer_user_id: str, comment: str | None, correlation_id: str | None = None
) -> None:
    platform = await _platform_for_plan(plan_id)
    session, service = await _build_publishing_service(platform)
    async with session:
        with _activity_correlation_scope(correlation_id):
            await service.finalize_rejected(uuid.UUID(plan_id), uuid.UUID(reviewer_user_id), comment)


@activity.defn
async def mark_approved_activity(plan_id: str, reviewer_user_id: str, correlation_id: str | None = None) -> None:
    platform = await _platform_for_plan(plan_id)
    session, service = await _build_publishing_service(platform)
    async with session:
        with _activity_correlation_scope(correlation_id):
            await service.mark_approved(uuid.UUID(plan_id), uuid.UUID(reviewer_user_id))


_STANDARD_RETRY = RetryPolicy(maximum_attempts=1)


@workflow.defn
class PublicationWorkflow:
    def __init__(self) -> None:
        self._review_decision: str | None = None
        self._review_comment: str | None = None
        self._reviewer_user_id: str | None = None

    @workflow.run
    async def run(self, input: PublicationWorkflowInput, scheduled_for_iso: str | None = None) -> PublicationWorkflowResult:
        capability = await workflow.execute_activity(
            check_capability_activity,
            args=[input.plan_id, input.correlation_id],
            start_to_close_timeout=timedelta(seconds=30),
            retry_policy=_STANDARD_RETRY,
        )
        if not capability["ok"]:
            return PublicationWorkflowResult(status="failed", reason=capability["error"])

        # Durable wait: survives worker restarts, same pattern as
        # GenerationWorkflow's review gate.
        await workflow.wait_condition(lambda: self._review_decision is not None)

        if self._review_decision != "approved":
            await workflow.execute_activity(
                finalize_rejected_publication_activity,
                args=[input.plan_id, self._reviewer_user_id, self._review_comment, input.correlation_id],
                start_to_close_timeout=timedelta(seconds=30),
                retry_policy=_STANDARD_RETRY,
            )
            return PublicationWorkflowResult(status="rejected", reason=self._review_comment)

        await workflow.execute_activity(
            mark_approved_activity,
            args=[input.plan_id, self._reviewer_user_id, input.correlation_id],
            start_to_close_timeout=timedelta(seconds=30),
            retry_policy=_STANDARD_RETRY,
        )

        if scheduled_for_iso:
            scheduled_for = datetime.fromisoformat(scheduled_for_iso)
            now = workflow.now()
            delay = (scheduled_for - now).total_seconds()
            if delay > 0:
                await asyncio.sleep(delay)

        dispatch = await workflow.execute_activity(
            dispatch_publish_activity,
            args=[input.plan_id, input.correlation_id],
            start_to_close_timeout=timedelta(seconds=60),
            retry_policy=_STANDARD_RETRY,
        )
        if not dispatch["ok"]:
            return PublicationWorkflowResult(status="failed", reason=dispatch["error"])

        reconciliation = await workflow.execute_activity(
            reconcile_activity,
            args=[input.plan_id, dispatch["attempt_id"], input.correlation_id],
            start_to_close_timeout=timedelta(seconds=30),
            retry_policy=_STANDARD_RETRY,
        )
        if reconciliation["matches_expected"]:
            return PublicationWorkflowResult(status="published")
        return PublicationWorkflowResult(
            status="failed", reason=f"reconciliation mismatch: {reconciliation['external_status']}"
        )

    @workflow.signal
    def submit_review(self, decision: str, reviewer_user_id: str, comment: str | None = None) -> None:
        self._review_decision = decision
        self._reviewer_user_id = reviewer_user_id
        self._review_comment = comment
