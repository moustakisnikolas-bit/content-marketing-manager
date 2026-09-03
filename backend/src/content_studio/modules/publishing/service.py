import uuid
from dataclasses import dataclass

import httpx
from sqlalchemy.ext.asyncio import AsyncSession

from content_studio.modules.analytics.ingestion_service import MetricsIngestionService
from content_studio.modules.creation.repository import CreationRepository
from content_studio.modules.governance.service import AuditService
from content_studio.modules.publishing.exceptions import PlatformDeleteRejected
from content_studio.modules.publishing.models import PlatformConnection
from content_studio.modules.publishing.repository import PublishingRepository
from content_studio.ports.object_storage import ObjectStoragePort
from content_studio.ports.secrets import SecretsPort
from content_studio.ports.social_platform import ConnectableAccount, OAuthToken, SocialPlatformPort

# content_type -> the capability name required to publish it directly.
_REQUIRED_CAPABILITY = {"text": "direct_publish_text", "image": "direct_publish_image"}

# Platforms delete_publication_plan() never attempts a real platform-side
# delete for — see that method's docstring. Instagram's Graph API needs a
# permission this app's OAuth product config can't currently grant.
_NO_PLATFORM_DELETE_SUPPORT = {"instagram"}


@dataclass(frozen=True)
class StepResult:
    ok: bool
    error: str | None = None
    attempt_id: str | None = None


@dataclass(frozen=True)
class ReconcileResult:
    matches_expected: bool
    external_status: str


@dataclass(frozen=True)
class PendingAccountSelection:
    """connect_platform()'s result when the exchanged token could publish
    as more than one account (Meta: every Facebook Page the user manages)
    — the caller must show a picker and call select_account() with the
    user's choice before a PlatformConnection exists. user_token_secret_ref
    is a *temporary* seal, deleted once select_account() finalizes."""

    user_token_secret_ref: str
    accounts: list[ConnectableAccount]


class PublishingService:
    """Called both from the API (connect/list) and from Temporal activities
    (workflows/publication.py) — same split as GenerationService in
    Phase 2."""

    def __init__(
        self,
        session: AsyncSession,
        *,
        platform_adapter: SocialPlatformPort,
        secrets: SecretsPort,
        object_storage: ObjectStoragePort,
    ) -> None:
        self._session = session
        self._repo = PublishingRepository(session)
        self._creation_repo = CreationRepository(session)
        self._audit = AuditService(session)
        self._platform_adapter = platform_adapter
        self._secrets = secrets
        self._object_storage = object_storage

    async def connect_platform(
        self,
        *,
        organization_id: uuid.UUID,
        workspace_id: uuid.UUID,
        user_id: uuid.UUID,
        platform: str,
        code: str,
    ) -> PlatformConnection | PendingAccountSelection:
        user_token = await self._platform_adapter.exchange_code_for_token(code=code)
        accounts = await self._platform_adapter.list_connectable_accounts(access_token=user_token.access_token)

        if len(accounts) > 1:
            # Genuinely ambiguous (Meta: multiple Facebook Pages) — defer
            # finalizing until the caller picks one via select_account().
            # Every single-account platform (and the stub) never reaches
            # this branch, so their behavior is unchanged.
            user_token_ref = await self._secrets.seal(value=user_token.access_token)
            return PendingAccountSelection(user_token_secret_ref=user_token_ref, accounts=accounts)

        return await self._finalize_connection(
            organization_id=organization_id, workspace_id=workspace_id, user_id=user_id, platform=platform,
            token=user_token,
        )

    async def select_account(
        self,
        *,
        organization_id: uuid.UUID,
        workspace_id: uuid.UUID,
        user_id: uuid.UUID,
        platform: str,
        user_token_secret_ref: str,
        external_account_id: str,
    ) -> PlatformConnection:
        user_access_token = await self._secrets.unseal(reference=user_token_secret_ref)
        final_token = await self._platform_adapter.resolve_account_token(
            access_token=user_access_token, external_account_id=external_account_id
        )
        connection = await self._finalize_connection(
            organization_id=organization_id, workspace_id=workspace_id, user_id=user_id, platform=platform,
            token=final_token,
        )
        await self._secrets.delete(reference=user_token_secret_ref)
        return connection

    async def _finalize_connection(
        self,
        *,
        organization_id: uuid.UUID,
        workspace_id: uuid.UUID,
        user_id: uuid.UUID,
        platform: str,
        token: OAuthToken,
    ) -> PlatformConnection:
        access_ref = await self._secrets.seal(value=token.access_token)
        refresh_ref = await self._secrets.seal(value=token.refresh_token) if token.refresh_token else None

        connection = await self._repo.create_connection(
            organization_id=organization_id,
            workspace_id=workspace_id,
            connected_by_user_id=user_id,
            platform=platform,
            external_account_id=token.external_account_id,
            external_account_name=token.external_account_name,
            access_token_secret_ref=access_ref,
            refresh_token_secret_ref=refresh_ref,
            scopes=token.scopes,
        )

        await self.refresh_capabilities(connection.id)

        await self._audit.record(
            event_type="publishing.connected",
            actor_type="user",
            actor_id=str(user_id),
            organization_id=organization_id,
            summary=f"Connected {platform} account '{token.external_account_name}'",
            payload={"connection_id": str(connection.id), "platform": platform},
        )
        await self._session.commit()
        return connection

    async def refresh_capabilities(self, connection_id: uuid.UUID) -> None:
        connection = await self._repo.get_connection_by_id(connection_id)
        assert connection is not None
        access_token = await self._secrets.unseal(reference=connection.access_token_secret_ref)
        results = await self._platform_adapter.resolve_capabilities(access_token=access_token)
        for result in results:
            await self._repo.upsert_capability(
                connection_id=connection.id,
                capability=result.capability,
                is_available=result.is_available,
                reason=result.reason,
            )
        await self._session.commit()

    async def check_capability(self, plan_id: uuid.UUID) -> StepResult:
        plan = await self._repo.get_publication_plan_by_id(plan_id)
        assert plan is not None
        item = await self._creation_repo.get_content_item_by_id(plan.content_item_id)
        assert item is not None

        required = "direct_publish_story" if plan.target_format == "story" else _REQUIRED_CAPABILITY.get(item.content_type)
        if required is None:
            await self._repo.update_plan_status(plan, "failed", failure_reason=f"unsupported content_type {item.content_type!r}")
            await self._session.commit()
            return StepResult(ok=False, error="unsupported content type")

        capability = await self._repo.get_capability(plan.platform_connection_id, required)
        if capability is None or not capability.is_available:
            reason = capability.reason if capability else "capability not resolved for this connection"
            await self._repo.update_plan_status(plan, "failed", failure_reason=reason)
            await self._session.commit()
            return StepResult(ok=False, error=reason)

        await self._repo.update_plan_status(plan, "pending_approval")
        await self._session.commit()
        return StepResult(ok=True)

    async def dispatch_publish(self, plan_id: uuid.UUID) -> StepResult:
        plan = await self._repo.get_publication_plan_by_id(plan_id)
        assert plan is not None
        item = await self._creation_repo.get_content_item_by_id(plan.content_item_id)
        assert item is not None
        package = await self._creation_repo.get_package_for_item(item.id)
        if package is None:
            await self._repo.update_plan_status(plan, "failed", failure_reason="content has no approved package")
            await self._session.commit()
            return StepResult(ok=False, error="content has no approved package")
        revision = await self._creation_repo.get_revision_by_id(package.selected_revision_id)
        assert revision is not None

        connection = await self._repo.get_connection_by_id(plan.platform_connection_id)
        assert connection is not None
        access_token = await self._secrets.unseal(reference=connection.access_token_secret_ref)

        attempt_number = await self._repo.count_attempts_for_plan(plan.id) + 1
        attempt = await self._repo.create_attempt(publication_plan_id=plan.id, attempt_number=attempt_number)
        await self._session.commit()

        try:
            if item.content_type == "text":
                result = await self._platform_adapter.publish_text(
                    access_token=access_token,
                    external_account_id=connection.external_account_id,
                    text=revision.text_body or "",
                )
            else:
                assert revision.asset_id is not None
                asset = await self._creation_repo.get_asset_by_id(revision.asset_id)
                assert asset is not None
                # A URL, not raw bytes — Instagram's Graph API creates media
                # containers by fetching the URL server-side, it has no
                # raw-upload path for images (see SocialPlatformPort.publish_image's
                # docstring). Must be internet-reachable on a real deployment.
                image_url = await self._object_storage.get_presigned_url(key=asset.storage_key)
                if plan.target_format == "story":
                    result = await self._platform_adapter.publish_story(
                        access_token=access_token,
                        external_account_id=connection.external_account_id,
                        image_url=image_url,
                    )
                else:
                    # Image revisions never get a text_body —
                    # generation_service.py doesn't produce an AI caption
                    # for images — so without this fallback every real
                    # Instagram/Facebook image post would ship with a
                    # genuinely empty caption. The item's own title is the
                    # closest thing to a caption that already exists.
                    result = await self._platform_adapter.publish_image(
                        access_token=access_token,
                        external_account_id=connection.external_account_id,
                        text=revision.text_body or item.title,
                        image_url=image_url,
                    )
        except Exception as exc:  # noqa: BLE001 — any platform-call failure is "attempt failed"
            await self._repo.complete_attempt(attempt, status="failed", error_message=str(exc))
            await self._repo.update_plan_status(plan, "failed", failure_reason=str(exc))
            await self._session.commit()
            return StepResult(ok=False, error=str(exc), attempt_id=str(attempt.id))

        await self._repo.complete_attempt(attempt, status="succeeded", external_post_id=result.external_post_id)
        await self._repo.update_plan_status(plan, "publishing")
        await self._audit.record(
            event_type="publishing.dispatched",
            actor_type="service",
            organization_id=plan.organization_id,
            summary=f"Published '{item.title}' to {connection.platform}",
            payload={"plan_id": str(plan.id), "external_post_id": result.external_post_id},
        )
        await self._session.commit()
        return StepResult(ok=True, attempt_id=str(attempt.id))

    async def reconcile(self, plan_id: uuid.UUID, attempt_id: uuid.UUID) -> ReconcileResult:
        plan = await self._repo.get_publication_plan_by_id(plan_id)
        assert plan is not None
        attempt = await self._repo.get_attempt_by_id(attempt_id)
        assert attempt is not None
        connection = await self._repo.get_connection_by_id(plan.platform_connection_id)
        assert connection is not None
        access_token = await self._secrets.unseal(reference=connection.access_token_secret_ref)

        assert attempt.external_post_id is not None, "reconcile() only runs after a successful dispatch"
        external_status = await self._platform_adapter.get_post_status(
            access_token=access_token, external_post_id=attempt.external_post_id
        )
        matches = external_status == "published"
        await self._repo.create_reconciliation(
            publication_attempt_id=attempt.id, matches_expected=matches, external_status=external_status
        )
        await self._repo.update_plan_status(plan, "published" if matches else "failed")
        await self._session.commit()

        if matches:
            # Best-effort: this is how metric_snapshots actually gets real
            # data going forward (previously only reachable via a manual,
            # never-called API endpoint) so suggest_weekly_schedule()
            # has real history to learn from. A failure here must never
            # undo reconcile()'s own already-committed result.
            ingestion = MetricsIngestionService(
                self._session, secrets=self._secrets, platform_adapter_factory=lambda _platform: self._platform_adapter
            )
            try:
                await ingestion.ingest_for_attempt(attempt.id)
            except Exception:  # noqa: BLE001, S110 — metrics ingestion is never allowed to break reconcile()
                pass

        return ReconcileResult(matches_expected=matches, external_status=external_status)

    async def finalize_rejected(self, plan_id: uuid.UUID, user_id: uuid.UUID, comment: str | None) -> None:
        plan = await self._repo.get_publication_plan_by_id(plan_id)
        assert plan is not None
        await self._repo.update_plan_status(plan, "rejected", failure_reason=comment)
        await self._audit.record(
            event_type="publishing.rejected",
            actor_type="user",
            actor_id=str(user_id),
            organization_id=plan.organization_id,
            summary="Publication plan rejected" + (f": {comment}" if comment else ""),
            payload={"plan_id": str(plan.id)},
        )
        await self._session.commit()

    async def mark_approved(self, plan_id: uuid.UUID, user_id: uuid.UUID) -> None:
        plan = await self._repo.get_publication_plan_by_id(plan_id)
        assert plan is not None
        await self._repo.approve_plan(plan, user_id)
        await self._repo.update_plan_status(plan, "approved")
        await self._session.commit()

    async def delete_publication_plan(self, plan_id: uuid.UUID, user_id: uuid.UUID) -> None:
        """Removes this app's own record of the plan — and, if it already
        published for real *and* the platform actually supports it, deletes
        the live post first. A plan that never successfully dispatched (no
        succeeded attempt) is just a local record with nothing to undo on
        the platform's side. The platform call (when attempted) must
        succeed, or raise, before the local record is deleted — never leave
        the app's tracking gone while a real post is still live.

        Instagram is deliberately excluded from the platform call: its
        Graph API requires a permission (confirmed live) this app's OAuth
        product config doesn't grant — requesting it 400s the login dialog
        itself with "Invalid Scopes" rather than just failing the delete,
        so there's no scope to add without a Meta App Dashboard change this
        code can't make. Instagram deletes are app-record-only until that's
        sorted out; Facebook is unaffected (different, already-granted
        permission)."""
        plan = await self._repo.get_publication_plan_by_id(plan_id)
        assert plan is not None

        attempts = await self._repo.list_attempts_for_plan(plan_id)
        succeeded = [a for a in attempts if a.status == "succeeded" and a.external_post_id is not None]
        external_post_id = succeeded[-1].external_post_id if succeeded else None

        connection = None
        removed_live_post = False
        if external_post_id is not None:
            connection = await self._repo.get_connection_by_id(plan.platform_connection_id)
            assert connection is not None
            if connection.platform not in _NO_PLATFORM_DELETE_SUPPORT:
                access_token = await self._secrets.unseal(reference=connection.access_token_secret_ref)
                try:
                    await self._platform_adapter.delete_post(
                        access_token=access_token, external_post_id=external_post_id
                    )
                except httpx.HTTPStatusError as exc:
                    raise PlatformDeleteRejected(connection.platform, exc.response.text[:300]) from exc
                removed_live_post = True

        if removed_live_post:
            summary_suffix = f" (also removed live post {external_post_id})"
        elif external_post_id is not None:
            summary_suffix = f" (app record only — live post {external_post_id} left on {connection.platform})"
        else:
            summary_suffix = ""

        await self._audit.record(
            event_type="publishing.deleted",
            actor_type="user",
            actor_id=str(user_id),
            organization_id=plan.organization_id,
            summary=f"Publication plan deleted{summary_suffix}",
            payload={
                "plan_id": str(plan_id), "external_post_id": external_post_id, "removed_live_post": removed_live_post,
            },
        )
        await self._repo.delete_plan(plan)
        await self._session.commit()
