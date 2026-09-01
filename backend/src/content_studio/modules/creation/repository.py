import uuid
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from content_studio.modules.creation.models import (
    Asset,
    ContentItem,
    ContentPackage,
    ContentRecipe,
    ContentRevision,
    GenerationAttempt,
    GenerationJob,
    Review,
    TextEditLearning,
)


class CreationRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    # -- Assets (Phase 1) ----------------------------------------------

    async def create_asset(
        self,
        *,
        organization_id: uuid.UUID,
        workspace_id: uuid.UUID,
        uploaded_by_user_id: uuid.UUID,
        storage_key: str,
        original_filename: str,
        content_type: str,
        byte_size: int,
    ) -> Asset:
        asset = Asset(
            organization_id=organization_id,
            workspace_id=workspace_id,
            uploaded_by_user_id=uploaded_by_user_id,
            storage_key=storage_key,
            original_filename=original_filename,
            content_type=content_type,
            byte_size=byte_size,
        )
        self._session.add(asset)
        await self._session.flush()
        return asset

    async def get_asset_by_id(self, asset_id: uuid.UUID) -> Asset | None:
        return await self._session.get(Asset, asset_id)

    async def list_assets_for_workspace(self, workspace_id: uuid.UUID) -> list[Asset]:
        result = await self._session.execute(
            select(Asset).where(Asset.workspace_id == workspace_id).order_by(Asset.created_at.desc())
        )
        return list(result.scalars().all())

    # -- Content recipes --------------------------------------------------

    async def get_recipe_by_id(self, recipe_id: uuid.UUID) -> ContentRecipe | None:
        return await self._session.get(ContentRecipe, recipe_id)

    async def get_active_recipe_for_content_type(self, content_type: str) -> ContentRecipe | None:
        # Ordered by most-recently-created: without an explicit order,
        # "LIMIT 1" over multiple active recipes for the same content_type
        # is not guaranteed stable across query plans — it happened to work
        # by insertion-order luck until enough recipes accumulated in the
        # same database for this to matter (multiple phases' tests each
        # seed their own "text" recipe into the same catalog table).
        result = await self._session.execute(
            select(ContentRecipe)
            .where(ContentRecipe.content_type == content_type, ContentRecipe.is_active.is_(True))
            .order_by(ContentRecipe.created_at.desc())
            .limit(1)
        )
        return result.scalar_one_or_none()

    async def create_recipe(
        self,
        *,
        name: str,
        content_type: str,
        provider: str,
        model: str,
        estimated_cost,
        params: dict | None = None,
    ) -> ContentRecipe:
        recipe = ContentRecipe(
            name=name,
            content_type=content_type,
            provider=provider,
            model=model,
            estimated_cost=estimated_cost,
            params=params or {},
        )
        self._session.add(recipe)
        await self._session.flush()
        return recipe

    # -- Content items ------------------------------------------------

    async def create_content_item(
        self,
        *,
        organization_id: uuid.UUID,
        workspace_id: uuid.UUID,
        created_by_user_id: uuid.UUID,
        content_type: str,
        title: str,
        brand_profile_id: uuid.UUID | None = None,
    ) -> ContentItem:
        item = ContentItem(
            organization_id=organization_id,
            workspace_id=workspace_id,
            created_by_user_id=created_by_user_id,
            content_type=content_type,
            title=title,
            brand_profile_id=brand_profile_id,
        )
        self._session.add(item)
        await self._session.flush()
        return item

    async def get_content_item_by_id(self, item_id: uuid.UUID) -> ContentItem | None:
        return await self._session.get(ContentItem, item_id)

    async def list_content_items_for_workspace(self, workspace_id: uuid.UUID) -> list[ContentItem]:
        result = await self._session.execute(
            select(ContentItem)
            .where(ContentItem.workspace_id == workspace_id)
            .order_by(ContentItem.created_at.desc())
        )
        return list(result.scalars().all())

    async def update_content_item_status(self, item: ContentItem, status: str) -> None:
        item.status = status
        await self._session.flush()

    # -- Generation jobs ------------------------------------------------

    async def create_generation_job(
        self,
        *,
        organization_id: uuid.UUID,
        workspace_id: uuid.UUID,
        content_item_id: uuid.UUID,
        recipe_id: uuid.UUID,
        requested_by_user_id: uuid.UUID,
        subscription_id: uuid.UUID,
        brief_text: str,
        reference_image_url: str | None = None,
    ) -> GenerationJob:
        job = GenerationJob(
            organization_id=organization_id,
            workspace_id=workspace_id,
            content_item_id=content_item_id,
            recipe_id=recipe_id,
            requested_by_user_id=requested_by_user_id,
            subscription_id=subscription_id,
            brief_text=brief_text,
            reference_image_url=reference_image_url,
        )
        self._session.add(job)
        await self._session.flush()
        return job

    async def get_generation_job_by_id(self, job_id: uuid.UUID) -> GenerationJob | None:
        return await self._session.get(GenerationJob, job_id)

    async def get_generation_jobs_by_ids(self, job_ids: list[uuid.UUID]) -> list[GenerationJob]:
        if not job_ids:
            return []
        result = await self._session.execute(select(GenerationJob).where(GenerationJob.id.in_(job_ids)))
        return list(result.scalars().all())

    async def list_generation_jobs_for_workspace(self, workspace_id: uuid.UUID) -> list[GenerationJob]:
        result = await self._session.execute(
            select(GenerationJob)
            .where(GenerationJob.workspace_id == workspace_id)
            .order_by(GenerationJob.created_at.desc())
        )
        return list(result.scalars().all())

    async def set_job_workflow_id(self, job: GenerationJob, workflow_id: str) -> None:
        job.temporal_workflow_id = workflow_id
        await self._session.flush()

    async def set_job_reservation_id(self, job: GenerationJob, reservation_id: uuid.UUID) -> None:
        job.cost_reservation_id = reservation_id
        await self._session.flush()

    async def update_job_status(
        self, job: GenerationJob, status: str, *, failure_reason: str | None = None
    ) -> None:
        job.status = status
        if failure_reason is not None:
            job.failure_reason = failure_reason
        await self._session.flush()

    # -- Generation attempts --------------------------------------------

    async def create_generation_attempt(
        self,
        *,
        generation_job_id: uuid.UUID,
        attempt_number: int,
        provider: str,
        model: str,
    ) -> GenerationAttempt:
        attempt = GenerationAttempt(
            generation_job_id=generation_job_id,
            attempt_number=attempt_number,
            provider=provider,
            model=model,
            status="dispatched",
            started_at=datetime.now(UTC),
        )
        self._session.add(attempt)
        await self._session.flush()
        return attempt

    async def complete_attempt(
        self, attempt: GenerationAttempt, *, status: str, error_message: str | None = None, actual_cost=None
    ) -> None:
        attempt.status = status
        attempt.error_message = error_message
        attempt.actual_cost = actual_cost
        attempt.completed_at = datetime.now(UTC)
        await self._session.flush()

    async def count_attempts_for_job(self, generation_job_id: uuid.UUID) -> int:
        result = await self._session.execute(
            select(GenerationAttempt).where(GenerationAttempt.generation_job_id == generation_job_id)
        )
        return len(result.scalars().all())

    # -- Content revisions ------------------------------------------------

    async def create_revision(
        self,
        *,
        content_item_id: uuid.UUID,
        generation_attempt_id: uuid.UUID | None,
        revision_number: int,
        kind: str = "draft_preview",
        text_body: str | None = None,
        asset_id: uuid.UUID | None = None,
    ) -> ContentRevision:
        revision = ContentRevision(
            content_item_id=content_item_id,
            generation_attempt_id=generation_attempt_id,
            revision_number=revision_number,
            kind=kind,
            text_body=text_body,
            asset_id=asset_id,
        )
        self._session.add(revision)
        await self._session.flush()
        return revision

    async def get_revision_by_id(self, revision_id: uuid.UUID) -> ContentRevision | None:
        return await self._session.get(ContentRevision, revision_id)

    async def promote_revision_to_final(self, revision: ContentRevision) -> None:
        revision.kind = "final_render"
        await self._session.flush()

    async def update_revision_text(self, revision: ContentRevision, text_body: str) -> None:
        revision.text_body = text_body
        await self._session.flush()

    async def next_revision_number(self, content_item_id: uuid.UUID) -> int:
        result = await self._session.execute(
            select(ContentRevision).where(ContentRevision.content_item_id == content_item_id)
        )
        return len(result.scalars().all()) + 1

    async def list_revisions_for_item(self, content_item_id: uuid.UUID) -> list[ContentRevision]:
        result = await self._session.execute(
            select(ContentRevision)
            .where(ContentRevision.content_item_id == content_item_id)
            .order_by(ContentRevision.revision_number)
        )
        return list(result.scalars().all())

    # -- Reviews ------------------------------------------------------

    async def create_review(
        self,
        *,
        content_revision_id: uuid.UUID,
        reviewer_user_id: uuid.UUID,
        decision: str,
        comment: str | None,
    ) -> Review:
        review = Review(
            content_revision_id=content_revision_id,
            reviewer_user_id=reviewer_user_id,
            decision=decision,
            comment=comment,
            created_at=datetime.now(UTC),
        )
        self._session.add(review)
        await self._session.flush()
        return review

    async def list_recent_rejection_comments_for_workspace(self, workspace_id: uuid.UUID, *, limit: int = 5) -> list[str]:
        """Feeds commerce/service.py's bulk text-brief construction with
        "avoid these previously flagged issues" guidance — same
        accumulated-context approach already used for recent-post style
        reference."""
        result = await self._session.execute(
            select(Review.comment)
            .join(ContentRevision, ContentRevision.id == Review.content_revision_id)
            .join(ContentItem, ContentItem.id == ContentRevision.content_item_id)
            .where(
                ContentItem.workspace_id == workspace_id,
                Review.decision == "rejected",
                Review.comment.isnot(None),
                Review.comment != "",
            )
            .order_by(Review.created_at.desc())
            .limit(limit)
        )
        return [comment for comment in result.scalars().all() if comment]

    # -- Text edit learnings ----------------------------------------------

    async def create_text_edit_learning(
        self,
        *,
        organization_id: uuid.UUID,
        workspace_id: uuid.UUID,
        source_content_revision_id: uuid.UUID,
        deleted_text: str,
    ) -> TextEditLearning:
        learning = TextEditLearning(
            organization_id=organization_id,
            workspace_id=workspace_id,
            source_content_revision_id=source_content_revision_id,
            deleted_text=deleted_text,
            created_at=datetime.now(UTC),
        )
        self._session.add(learning)
        await self._session.flush()
        return learning

    async def list_recent_text_edit_learnings_for_workspace(
        self, workspace_id: uuid.UUID, *, limit: int = 10
    ) -> list[str]:
        result = await self._session.execute(
            select(TextEditLearning.deleted_text)
            .where(TextEditLearning.workspace_id == workspace_id)
            .order_by(TextEditLearning.created_at.desc())
            .limit(limit)
        )
        return list(result.scalars().all())

    # -- Content packages ------------------------------------------------

    async def create_package(
        self, *, content_item_id: uuid.UUID, selected_revision_id: uuid.UUID
    ) -> ContentPackage:
        package = ContentPackage(
            content_item_id=content_item_id,
            selected_revision_id=selected_revision_id,
            packaged_at=datetime.now(UTC),
        )
        self._session.add(package)
        await self._session.flush()
        return package

    async def get_package_for_item(self, content_item_id: uuid.UUID) -> ContentPackage | None:
        result = await self._session.execute(
            select(ContentPackage).where(ContentPackage.content_item_id == content_item_id)
        )
        return result.scalar_one_or_none()
