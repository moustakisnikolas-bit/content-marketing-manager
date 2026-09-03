import uuid
from dataclasses import dataclass
from datetime import timedelta

from temporalio import activity, workflow
from temporalio.common import RetryPolicy

# Phase 2's real generation-lifecycle workflow — proves the pattern
# sketched by Phase 1's PingWorkflow, now carrying actual business logic:
# reserve -> dispatch -> quality gate -> durable human-review wait ->
# settle/package. Every activity builds its own DB session and adapters
# (imported inside the function body, not at module level, so the
# workflow-sandbox import scan never sees SQLAlchemy/httpx) — same pattern
# as workflows/ping.py.


@dataclass
class GenerationWorkflowInput:
    job_id: str


@dataclass
class GenerationWorkflowResult:
    status: str
    package_id: str | None = None
    reason: str | None = None


async def _build_generation_service():
    from content_studio.adapters.factory import (
        get_ai_audio_adapter,
        get_ai_image_adapter,
        get_ai_text_adapter,
    )
    from content_studio.adapters.object_storage.seaweedfs import SeaweedFSObjectStorage
    from content_studio.config import get_settings
    from content_studio.db.session import SessionLocal
    from content_studio.modules.creation.generation_service import GenerationService

    settings = get_settings()
    session = SessionLocal()
    service = GenerationService(
        session,
        ai_text=get_ai_text_adapter(settings),
        ai_image=get_ai_image_adapter(settings),
        ai_audio=get_ai_audio_adapter(settings),
        object_storage=SeaweedFSObjectStorage(settings),
    )
    return session, service


@activity.defn
async def reserve_generation_cost(job_id: str) -> dict:
    session, service = await _build_generation_service()
    async with session:
        result = await service.reserve_cost(uuid.UUID(job_id))
        return {"ok": result.ok, "error": result.error}


@activity.defn
async def dispatch_generation(job_id: str) -> dict:
    session, service = await _build_generation_service()
    async with session:
        result = await service.dispatch(uuid.UUID(job_id))
        return {"ok": result.ok, "error": result.error, "revision_id": result.revision_id}


@activity.defn
async def run_quality_gate_activity(job_id: str, revision_id: str) -> dict:
    session, service = await _build_generation_service()
    async with session:
        result = await service.run_quality_gate(uuid.UUID(job_id), uuid.UUID(revision_id))
        return {"passed": result.passed, "violations": result.violations}


@activity.defn
async def finalize_approved_activity(
    job_id: str, revision_id: str, reviewer_user_id: str, comment: str | None
) -> str:
    session, service = await _build_generation_service()
    async with session:
        return await service.finalize_approved(
            uuid.UUID(job_id), uuid.UUID(revision_id), uuid.UUID(reviewer_user_id), comment
        )


@activity.defn
async def finalize_rejected_activity(
    job_id: str, revision_id: str, reviewer_user_id: str, comment: str | None
) -> None:
    session, service = await _build_generation_service()
    async with session:
        await service.finalize_rejected(
            uuid.UUID(job_id), uuid.UUID(revision_id), uuid.UUID(reviewer_user_id), comment
        )


_STANDARD_RETRY = RetryPolicy(maximum_attempts=1)


@workflow.defn
class GenerationWorkflow:
    def __init__(self) -> None:
        self._review_decision: str | None = None
        self._review_comment: str | None = None
        self._reviewer_user_id: str | None = None

    @workflow.run
    async def run(self, input: GenerationWorkflowInput) -> GenerationWorkflowResult:
        reserve = await workflow.execute_activity(
            reserve_generation_cost,
            input.job_id,
            start_to_close_timeout=timedelta(seconds=30),
            retry_policy=_STANDARD_RETRY,
        )
        if not reserve["ok"]:
            return GenerationWorkflowResult(status="failed", reason=reserve["error"])

        dispatch = await workflow.execute_activity(
            dispatch_generation,
            input.job_id,
            # 300s, not 120 — an image generation now runs a second,
            # sequential Replicate prediction (the resolution upscale pass
            # in adapters/ai_image/replicate.py), each with its own ~60s
            # poll ceiling, plus that pass's own 429 retry backoff (up to
            # 30s — confirmed live that its rate limit is tight enough to
            # hit on every single call); 120s left no headroom at all.
            start_to_close_timeout=timedelta(seconds=300),
            retry_policy=_STANDARD_RETRY,
        )
        if not dispatch["ok"]:
            return GenerationWorkflowResult(status="failed", reason=dispatch["error"])

        revision_id = dispatch["revision_id"]
        gate = await workflow.execute_activity(
            run_quality_gate_activity,
            args=[input.job_id, revision_id],
            start_to_close_timeout=timedelta(seconds=30),
            retry_policy=_STANDARD_RETRY,
        )
        if not gate["passed"]:
            return GenerationWorkflowResult(status="quality_gate_failed", reason="; ".join(gate["violations"]))

        # Durable wait: this workflow can sit here for hours/days across
        # worker restarts — Temporal replays history rather than holding a
        # thread/connection open — until a human calls the /review endpoint,
        # which delivers this signal.
        await workflow.wait_condition(lambda: self._review_decision is not None)

        if self._review_decision == "approved":
            package_id = await workflow.execute_activity(
                finalize_approved_activity,
                args=[input.job_id, revision_id, self._reviewer_user_id, self._review_comment],
                start_to_close_timeout=timedelta(seconds=30),
                retry_policy=_STANDARD_RETRY,
            )
            return GenerationWorkflowResult(status="approved", package_id=package_id)

        await workflow.execute_activity(
            finalize_rejected_activity,
            args=[input.job_id, revision_id, self._reviewer_user_id, self._review_comment],
            start_to_close_timeout=timedelta(seconds=30),
            retry_policy=_STANDARD_RETRY,
        )
        return GenerationWorkflowResult(status="rejected", reason=self._review_comment)

    @workflow.signal
    def submit_review(self, decision: str, reviewer_user_id: str, comment: str | None = None) -> None:
        self._review_decision = decision
        self._reviewer_user_id = reviewer_user_id
        self._review_comment = comment
