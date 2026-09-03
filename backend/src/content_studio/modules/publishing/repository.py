import uuid
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from content_studio.modules.publishing.models import (
    EffectiveCapability,
    PlatformConnection,
    PublicationAttempt,
    PublicationPlan,
    Reconciliation,
)


class PublishingRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    # -- Platform connections --------------------------------------------

    async def create_connection(
        self,
        *,
        organization_id: uuid.UUID,
        workspace_id: uuid.UUID,
        connected_by_user_id: uuid.UUID,
        platform: str,
        external_account_id: str,
        external_account_name: str,
        access_token_secret_ref: str,
        refresh_token_secret_ref: str | None,
        scopes: list[str],
    ) -> PlatformConnection:
        connection = PlatformConnection(
            organization_id=organization_id,
            workspace_id=workspace_id,
            connected_by_user_id=connected_by_user_id,
            platform=platform,
            external_account_id=external_account_id,
            external_account_name=external_account_name,
            access_token_secret_ref=access_token_secret_ref,
            refresh_token_secret_ref=refresh_token_secret_ref,
            scopes=scopes,
        )
        self._session.add(connection)
        await self._session.flush()
        return connection

    async def get_connection_by_id(self, connection_id: uuid.UUID) -> PlatformConnection | None:
        return await self._session.get(PlatformConnection, connection_id)

    async def list_connections_for_workspace(self, workspace_id: uuid.UUID) -> list[PlatformConnection]:
        result = await self._session.execute(
            select(PlatformConnection).where(PlatformConnection.workspace_id == workspace_id)
        )
        return list(result.scalars().all())

    # -- Effective capabilities ------------------------------------------

    async def upsert_capability(
        self, *, connection_id: uuid.UUID, capability: str, is_available: bool, reason: str | None
    ) -> EffectiveCapability:
        result = await self._session.execute(
            select(EffectiveCapability).where(
                EffectiveCapability.platform_connection_id == connection_id,
                EffectiveCapability.capability == capability,
            )
        )
        existing = result.scalar_one_or_none()
        now = datetime.now(UTC)
        if existing is not None:
            existing.is_available = is_available
            existing.reason = reason
            existing.resolved_at = now
            await self._session.flush()
            return existing

        row = EffectiveCapability(
            platform_connection_id=connection_id,
            capability=capability,
            is_available=is_available,
            reason=reason,
            resolved_at=now,
        )
        self._session.add(row)
        await self._session.flush()
        return row

    async def list_capabilities_for_connection(self, connection_id: uuid.UUID) -> list[EffectiveCapability]:
        result = await self._session.execute(
            select(EffectiveCapability).where(EffectiveCapability.platform_connection_id == connection_id)
        )
        return list(result.scalars().all())

    async def get_capability(self, connection_id: uuid.UUID, capability: str) -> EffectiveCapability | None:
        result = await self._session.execute(
            select(EffectiveCapability).where(
                EffectiveCapability.platform_connection_id == connection_id,
                EffectiveCapability.capability == capability,
            )
        )
        return result.scalar_one_or_none()

    # -- Publication plans ------------------------------------------------

    async def create_publication_plan(
        self,
        *,
        organization_id: uuid.UUID,
        workspace_id: uuid.UUID,
        content_item_id: uuid.UUID,
        platform_connection_id: uuid.UUID,
        created_by_user_id: uuid.UUID,
        scheduled_for: datetime | None,
        target_format: str = "post",
    ) -> PublicationPlan:
        plan = PublicationPlan(
            organization_id=organization_id,
            workspace_id=workspace_id,
            content_item_id=content_item_id,
            platform_connection_id=platform_connection_id,
            created_by_user_id=created_by_user_id,
            scheduled_for=scheduled_for,
            target_format=target_format,
        )
        self._session.add(plan)
        await self._session.flush()
        return plan

    async def get_publication_plan_by_id(self, plan_id: uuid.UUID) -> PublicationPlan | None:
        return await self._session.get(PublicationPlan, plan_id)

    async def list_publication_plans_for_workspace(self, workspace_id: uuid.UUID) -> list[PublicationPlan]:
        result = await self._session.execute(
            select(PublicationPlan)
            .where(PublicationPlan.workspace_id == workspace_id)
            .order_by(PublicationPlan.created_at.desc())
        )
        return list(result.scalars().all())

    async def set_plan_workflow_id(self, plan: PublicationPlan, workflow_id: str) -> None:
        plan.temporal_workflow_id = workflow_id
        await self._session.flush()

    async def update_plan_status(
        self, plan: PublicationPlan, status: str, *, failure_reason: str | None = None
    ) -> None:
        plan.status = status
        if failure_reason is not None:
            plan.failure_reason = failure_reason
        await self._session.flush()

    async def approve_plan(self, plan: PublicationPlan, approved_by_user_id: uuid.UUID) -> None:
        plan.approved_by_user_id = approved_by_user_id
        plan.approved_at = datetime.now(UTC)
        await self._session.flush()

    async def delete_plan(self, plan: PublicationPlan) -> None:
        # Attempts/reconciliations cascade (ondelete="CASCADE" on both FKs,
        # see models.py) — this is purely the app's own record, never the
        # platform-side post itself, which the caller must delete
        # separately through the SocialPlatformPort before calling this.
        await self._session.delete(plan)
        await self._session.flush()

    # -- Publication attempts --------------------------------------------

    async def create_attempt(self, *, publication_plan_id: uuid.UUID, attempt_number: int) -> PublicationAttempt:
        attempt = PublicationAttempt(
            publication_plan_id=publication_plan_id,
            attempt_number=attempt_number,
            status="dispatched",
            started_at=datetime.now(UTC),
        )
        self._session.add(attempt)
        await self._session.flush()
        return attempt

    async def complete_attempt(
        self,
        attempt: PublicationAttempt,
        *,
        status: str,
        external_post_id: str | None = None,
        error_message: str | None = None,
    ) -> None:
        attempt.status = status
        attempt.external_post_id = external_post_id
        attempt.error_message = error_message
        attempt.completed_at = datetime.now(UTC)
        await self._session.flush()

    async def count_attempts_for_plan(self, plan_id: uuid.UUID) -> int:
        result = await self._session.execute(
            select(PublicationAttempt).where(PublicationAttempt.publication_plan_id == plan_id)
        )
        return len(result.scalars().all())

    async def list_attempts_for_plan(self, plan_id: uuid.UUID) -> list[PublicationAttempt]:
        result = await self._session.execute(
            select(PublicationAttempt)
            .where(PublicationAttempt.publication_plan_id == plan_id)
            .order_by(PublicationAttempt.attempt_number)
        )
        return list(result.scalars().all())

    async def get_attempt_by_id(self, attempt_id: uuid.UUID) -> PublicationAttempt | None:
        return await self._session.get(PublicationAttempt, attempt_id)

    # -- Reconciliation ------------------------------------------------

    async def create_reconciliation(
        self,
        *,
        publication_attempt_id: uuid.UUID,
        matches_expected: bool,
        external_status: str,
        notes: str | None = None,
    ) -> Reconciliation:
        reconciliation = Reconciliation(
            publication_attempt_id=publication_attempt_id,
            checked_at=datetime.now(UTC),
            matches_expected=matches_expected,
            external_status=external_status,
            notes=notes,
        )
        self._session.add(reconciliation)
        await self._session.flush()
        return reconciliation

    async def list_reconciliations_for_attempt(self, attempt_id: uuid.UUID) -> list[Reconciliation]:
        result = await self._session.execute(
            select(Reconciliation).where(Reconciliation.publication_attempt_id == attempt_id)
        )
        return list(result.scalars().all())
