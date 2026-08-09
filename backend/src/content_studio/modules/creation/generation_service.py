import uuid
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from content_studio.modules.billing.exceptions import InsufficientCredits
from content_studio.modules.billing.service import LedgerService
from content_studio.modules.creation.quality_gate import check_text_against_brand_rules
from content_studio.modules.creation.repository import CreationRepository
from content_studio.modules.governance.service import AuditService
from content_studio.modules.identity.models import BrandRule
from content_studio.ports.ai_audio import AIAudioPort
from content_studio.ports.ai_image import AIImagePort
from content_studio.ports.ai_text import AITextPort
from content_studio.ports.object_storage import ObjectStoragePort


@dataclass(frozen=True)
class StepResult:
    ok: bool
    error: str | None = None
    revision_id: str | None = None
    attempt_id: str | None = None


@dataclass(frozen=True)
class QualityGateStepResult:
    passed: bool
    violations: list[str]


class GenerationService:
    """Called from Temporal activities (workflows/generation.py) — each
    method is one atomic step of the brief -> recipe -> estimate -> preview
    -> quality gate -> review -> package lifecycle from
    05_AI_CONTENT_CREATION_MODULE.md. Every method commits its own
    transaction since each runs as a separate Temporal activity."""

    def __init__(
        self,
        session: AsyncSession,
        *,
        ai_text: AITextPort,
        ai_image: AIImagePort,
        object_storage: ObjectStoragePort,
        ai_audio: AIAudioPort | None = None,
    ) -> None:
        self._session = session
        self._repo = CreationRepository(session)
        self._ledger = LedgerService(session)
        self._audit = AuditService(session)
        self._ai_text = ai_text
        self._ai_image = ai_image
        self._ai_audio = ai_audio
        self._object_storage = object_storage

    async def reserve_cost(self, job_id: uuid.UUID) -> StepResult:
        job = await self._repo.get_generation_job_by_id(job_id)
        if job is None:
            return StepResult(ok=False, error="job not found")

        recipe = await self._repo.get_recipe_by_id(job.recipe_id)
        assert recipe is not None

        try:
            reservation = await self._ledger.reserve(
                organization_id=job.organization_id,
                subscription_id=job.subscription_id,
                amount=recipe.estimated_cost,
                reference=f"generation_job:{job.id}",
                idempotency_key=f"generation_job:{job.id}",
            )
        except InsufficientCredits as exc:
            await self._repo.update_job_status(job, "failed", failure_reason=str(exc))
            await self._session.commit()
            return StepResult(ok=False, error=str(exc))

        await self._repo.set_job_reservation_id(job, reservation.id)
        await self._repo.update_job_status(job, "generating")
        await self._session.commit()
        return StepResult(ok=True)

    async def dispatch(self, job_id: uuid.UUID) -> StepResult:
        job = await self._repo.get_generation_job_by_id(job_id)
        assert job is not None
        recipe = await self._repo.get_recipe_by_id(job.recipe_id)
        assert recipe is not None
        item = await self._repo.get_content_item_by_id(job.content_item_id)
        assert item is not None

        attempt_number = await self._repo.count_attempts_for_job(job.id) + 1
        attempt = await self._repo.create_generation_attempt(
            generation_job_id=job.id, attempt_number=attempt_number, provider=recipe.provider, model=recipe.model
        )
        await self._session.commit()

        try:
            revision = await self._generate_revision(job=job, recipe=recipe, item=item, attempt_id=attempt.id)
        except Exception as exc:  # noqa: BLE001 — provider calls fail in many ways; all are "attempt failed"
            await self._repo.complete_attempt(attempt, status="failed", error_message=str(exc))
            assert job.cost_reservation_id is not None
            await self._ledger.release(reservation_id=job.cost_reservation_id)
            await self._repo.update_job_status(job, "failed", failure_reason=str(exc))
            await self._session.commit()
            return StepResult(ok=False, error=str(exc), attempt_id=str(attempt.id))

        await self._repo.complete_attempt(attempt, status="succeeded", actual_cost=recipe.estimated_cost)
        assert job.cost_reservation_id is not None
        await self._ledger.settle(reservation_id=job.cost_reservation_id, actual_amount=recipe.estimated_cost)
        await self._audit.record(
            event_type="content.generated",
            actor_type="service",
            organization_id=job.organization_id,
            summary=f"Generated {item.content_type} draft for '{item.title}'",
            payload={"job_id": str(job.id), "revision_id": str(revision.id), "provider": recipe.provider},
        )
        await self._session.commit()
        return StepResult(ok=True, revision_id=str(revision.id), attempt_id=str(attempt.id))

    async def _generate_revision(self, *, job, recipe, item, attempt_id: uuid.UUID):
        revision_number = await self._repo.next_revision_number(item.id)

        if item.content_type == "text":
            text = await self._ai_text.generate_text(prompt=job.brief_text, model=recipe.model, params=recipe.params)
            return await self._repo.create_revision(
                content_item_id=item.id,
                generation_attempt_id=attempt_id,
                revision_number=revision_number,
                text_body=text,
            )

        if item.content_type == "image":
            image_bytes = await self._ai_image.generate_image(
                prompt=job.brief_text, model=recipe.model, params=recipe.params
            )
            storage_key = f"generated/{job.organization_id}/{uuid.uuid4()}.png"
            await self._object_storage.put_object(key=storage_key, data=image_bytes, content_type="image/png")
            asset = await self._repo.create_asset(
                organization_id=job.organization_id,
                workspace_id=job.workspace_id,
                uploaded_by_user_id=job.requested_by_user_id,
                storage_key=storage_key,
                original_filename=f"{item.title}.png",
                content_type="image/png",
                byte_size=len(image_bytes),
            )
            return await self._repo.create_revision(
                content_item_id=item.id,
                generation_attempt_id=attempt_id,
                revision_number=revision_number,
                asset_id=asset.id,
            )

        if item.content_type == "audio":
            if self._ai_audio is None:
                raise RuntimeError("no AIAudioPort configured for this GenerationService instance")
            audio_bytes = await self._ai_audio.generate_audio(
                prompt=job.brief_text, model=recipe.model, params=recipe.params
            )
            storage_key = f"generated/{job.organization_id}/{uuid.uuid4()}.wav"
            await self._object_storage.put_object(key=storage_key, data=audio_bytes, content_type="audio/wav")
            asset = await self._repo.create_asset(
                organization_id=job.organization_id,
                workspace_id=job.workspace_id,
                uploaded_by_user_id=job.requested_by_user_id,
                storage_key=storage_key,
                original_filename=f"{item.title}.wav",
                content_type="audio/wav",
                byte_size=len(audio_bytes),
            )
            return await self._repo.create_revision(
                content_item_id=item.id,
                generation_attempt_id=attempt_id,
                revision_number=revision_number,
                asset_id=asset.id,
            )

        raise ValueError(f"unsupported content_type {item.content_type!r}")

    async def run_quality_gate(self, job_id: uuid.UUID, revision_id: uuid.UUID) -> QualityGateStepResult:
        job = await self._repo.get_generation_job_by_id(job_id)
        assert job is not None
        item = await self._repo.get_content_item_by_id(job.content_item_id)
        assert item is not None
        revision = await self._repo.get_revision_by_id(revision_id)
        assert revision is not None

        if item.content_type != "text" or item.brand_profile_id is None or revision.text_body is None:
            # No text or no brand profile attached — nothing to check
            # against yet. Media-content quality gates (rights/moderation
            # checks) are a later extension, not Phase 2 scope.
            await self._repo.update_job_status(job, "awaiting_review")
            await self._session.commit()
            return QualityGateStepResult(passed=True, violations=[])

        result = await self._session.execute(
            select(BrandRule).where(BrandRule.brand_profile_id == item.brand_profile_id)
        )
        rules = list(result.scalars().all())
        gate_result = check_text_against_brand_rules(revision.text_body, rules)

        if gate_result.passed:
            await self._repo.update_job_status(job, "awaiting_review")
        else:
            await self._repo.update_job_status(
                job, "quality_gate_failed", failure_reason="; ".join(gate_result.violations)
            )
            await self._audit.record(
                event_type="content.quality_gate_failed",
                actor_type="service",
                organization_id=job.organization_id,
                summary=f"Quality gate blocked '{item.title}': {'; '.join(gate_result.violations)}",
                payload={"job_id": str(job.id), "revision_id": str(revision.id)},
            )
        await self._session.commit()
        return QualityGateStepResult(passed=gate_result.passed, violations=gate_result.violations)

    async def finalize_approved(
        self, job_id: uuid.UUID, revision_id: uuid.UUID, reviewer_user_id: uuid.UUID, comment: str | None
    ) -> str:
        job = await self._repo.get_generation_job_by_id(job_id)
        assert job is not None
        revision = await self._repo.get_revision_by_id(revision_id)
        assert revision is not None

        await self._repo.create_review(
            content_revision_id=revision.id, reviewer_user_id=reviewer_user_id, decision="approved", comment=comment
        )
        await self._repo.promote_revision_to_final(revision)
        package = await self._repo.create_package(
            content_item_id=job.content_item_id, selected_revision_id=revision.id
        )
        item = await self._repo.get_content_item_by_id(job.content_item_id)
        assert item is not None
        await self._repo.update_content_item_status(item, "approved")
        await self._repo.update_job_status(job, "approved")
        await self._audit.record(
            event_type="content.approved",
            actor_type="user",
            actor_id=str(reviewer_user_id),
            organization_id=job.organization_id,
            summary=f"Approved and packaged '{item.title}'",
            payload={"job_id": str(job.id), "package_id": str(package.id)},
        )
        await self._session.commit()
        return str(package.id)

    async def finalize_rejected(
        self, job_id: uuid.UUID, revision_id: uuid.UUID, reviewer_user_id: uuid.UUID, comment: str | None
    ) -> None:
        job = await self._repo.get_generation_job_by_id(job_id)
        assert job is not None
        await self._repo.create_review(
            content_revision_id=revision_id, reviewer_user_id=reviewer_user_id, decision="rejected", comment=comment
        )
        item = await self._repo.get_content_item_by_id(job.content_item_id)
        assert item is not None
        await self._repo.update_content_item_status(item, "rejected")
        await self._repo.update_job_status(job, "rejected", failure_reason=comment)
        await self._audit.record(
            event_type="content.rejected",
            actor_type="user",
            actor_id=str(reviewer_user_id),
            organization_id=job.organization_id,
            summary=f"Rejected '{item.title}'" + (f": {comment}" if comment else ""),
            payload={"job_id": str(job.id)},
        )
        await self._session.commit()
