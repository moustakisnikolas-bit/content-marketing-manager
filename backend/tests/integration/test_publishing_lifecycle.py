import uuid
from decimal import Decimal

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from content_studio.modules.billing.repository import BillingRepository
from content_studio.modules.billing.service import LedgerService
from content_studio.modules.creation.generation_service import GenerationService
from content_studio.modules.creation.repository import CreationRepository
from content_studio.modules.identity.service import IdentityService
from content_studio.modules.publishing.exceptions import PlatformDeleteRejected
from content_studio.modules.publishing.repository import PublishingRepository
from content_studio.modules.publishing.service import PendingAccountSelection, PublishingService
from content_studio.ports.social_platform import CapabilityResult, ConnectableAccount
from tests.fakes.ai_image import FakeAIImage
from tests.fakes.ai_text import FakeAIText
from tests.fakes.object_storage import FakeObjectStorage
from tests.fakes.secrets import FakeSecrets
from tests.fakes.social_platform import FakeSocialPlatform

pytestmark = pytest.mark.asyncio


async def _seed_workspace(session: AsyncSession, *, allowance: Decimal = Decimal(100)) -> dict:
    identity = IdentityService(session)
    email = f"pub-{uuid.uuid4().hex[:12]}@example.com"
    signup = await identity.signup(
        email=email, password="correct-horse-battery", display_name="Pub Test", organization_name="Pub Org"
    )

    billing_repo = BillingRepository(session)
    plan_slug = f"plan-{uuid.uuid4().hex[:8]}"
    plan = await billing_repo.create_plan(
        name=plan_slug, slug=plan_slug, monthly_price=Decimal("39.00"), monthly_credit_allowance=allowance
    )
    await session.commit()

    ledger = LedgerService(session)
    subscription_id = await ledger.open_subscription(organization_id=signup.organization.id, plan_slug=plan.slug)

    return {
        "organization_id": signup.organization.id,
        "workspace_id": signup.workspace.id,
        "user_id": signup.user.id,
        "subscription_id": subscription_id,
    }


async def _seed_approved_text_item(session: AsyncSession, ctx: dict) -> uuid.UUID:
    """Reuses Phase 2's generation lifecycle to get a real approved
    ContentItem + ContentPackage to publish, matching how this would
    actually happen in production (publishing always operates on approved
    content)."""
    repo = CreationRepository(session)
    recipe = await repo.create_recipe(
        name=f"recipe-{uuid.uuid4().hex[:8]}", content_type="text", provider="openrouter", model="test-model",
        estimated_cost=Decimal("0.5"),
    )
    item = await repo.create_content_item(
        organization_id=ctx["organization_id"], workspace_id=ctx["workspace_id"],
        created_by_user_id=ctx["user_id"], content_type="text", title="Launch announcement",
    )
    job = await repo.create_generation_job(
        organization_id=ctx["organization_id"], workspace_id=ctx["workspace_id"], content_item_id=item.id,
        recipe_id=recipe.id, requested_by_user_id=ctx["user_id"], subscription_id=ctx["subscription_id"],
        brief_text="Announce our new product launch",
    )
    await session.commit()

    gen_service = GenerationService(
        session, ai_text=FakeAIText(fixed_response="Our new product is here!"), ai_image=FakeAIImage(),
        object_storage=FakeObjectStorage(),
    )
    await gen_service.reserve_cost(job.id)
    dispatch_result = await gen_service.dispatch(job.id)
    await gen_service.run_quality_gate(job.id, uuid.UUID(dispatch_result.revision_id))
    await gen_service.finalize_approved(job.id, uuid.UUID(dispatch_result.revision_id), ctx["user_id"], "ship it")

    return item.id


def _service(session: AsyncSession, *, platform_adapter=None, secrets=None, object_storage=None) -> PublishingService:
    return PublishingService(
        session,
        platform_adapter=platform_adapter or FakeSocialPlatform(),
        secrets=secrets or FakeSecrets(),
        object_storage=object_storage or FakeObjectStorage(),
    )


async def test_connect_platform_seals_tokens_and_resolves_capabilities(db_session: AsyncSession) -> None:
    ctx = await _seed_workspace(db_session)
    secrets = FakeSecrets()
    platform_adapter = FakeSocialPlatform(
        capabilities=[
            CapabilityResult(capability="direct_publish_text", is_available=True),
            CapabilityResult(capability="direct_publish_image", is_available=False, reason="needs business account"),
        ]
    )
    service = _service(db_session, platform_adapter=platform_adapter, secrets=secrets)

    connection = await service.connect_platform(
        organization_id=ctx["organization_id"], workspace_id=ctx["workspace_id"], user_id=ctx["user_id"],
        platform="facebook", code="fake-code",
    )

    assert connection.external_account_name == "Fake Account"
    # The token is never stored in plaintext — only an opaque reference.
    assert connection.access_token_secret_ref in secrets.store
    assert secrets.store[connection.access_token_secret_ref] == "fake-access-token"

    repo = PublishingRepository(db_session)
    capabilities = await repo.list_capabilities_for_connection(connection.id)
    by_name = {c.capability: c for c in capabilities}
    assert by_name["direct_publish_text"].is_available is True
    assert by_name["direct_publish_image"].is_available is False
    assert by_name["direct_publish_image"].reason == "needs business account"


async def test_connect_platform_defers_when_multiple_accounts(db_session: AsyncSession) -> None:
    ctx = await _seed_workspace(db_session)
    secrets = FakeSecrets()
    accounts = [
        ConnectableAccount(external_account_id="page-1", external_account_name="First Page"),
        ConnectableAccount(external_account_id="page-2", external_account_name="Second Page"),
    ]
    platform_adapter = FakeSocialPlatform(accounts=accounts)
    service = _service(db_session, platform_adapter=platform_adapter, secrets=secrets)

    result = await service.connect_platform(
        organization_id=ctx["organization_id"], workspace_id=ctx["workspace_id"], user_id=ctx["user_id"],
        platform="facebook", code="fake-code",
    )

    assert isinstance(result, PendingAccountSelection)
    assert {a.external_account_id for a in result.accounts} == {"page-1", "page-2"}
    # The user-level token is sealed (never left in plaintext) but no
    # PlatformConnection exists yet — that's select_account()'s job.
    assert result.user_token_secret_ref in secrets.store
    repo = PublishingRepository(db_session)
    connections = await repo.list_connections_for_workspace(ctx["workspace_id"])
    assert connections == []

    connection = await service.select_account(
        organization_id=ctx["organization_id"], workspace_id=ctx["workspace_id"], user_id=ctx["user_id"],
        platform="facebook", user_token_secret_ref=result.user_token_secret_ref, external_account_id="page-2",
    )

    assert connection.external_account_id == "page-2"
    # The temporary user-level secret is cleaned up once finalized.
    assert result.user_token_secret_ref not in secrets.store
    connections = await repo.list_connections_for_workspace(ctx["workspace_id"])
    assert len(connections) == 1


async def test_check_capability_fails_when_unavailable(db_session: AsyncSession) -> None:
    ctx = await _seed_workspace(db_session)
    item_id = await _seed_approved_text_item(db_session, ctx)

    platform_adapter = FakeSocialPlatform(
        capabilities=[CapabilityResult(capability="direct_publish_text", is_available=False, reason="not approved")]
    )
    service = _service(db_session, platform_adapter=platform_adapter)
    connection = await service.connect_platform(
        organization_id=ctx["organization_id"], workspace_id=ctx["workspace_id"], user_id=ctx["user_id"],
        platform="tiktok", code="fake-code",
    )

    repo = PublishingRepository(db_session)
    plan = await repo.create_publication_plan(
        organization_id=ctx["organization_id"], workspace_id=ctx["workspace_id"], content_item_id=item_id,
        platform_connection_id=connection.id, created_by_user_id=ctx["user_id"], scheduled_for=None,
    )
    await db_session.commit()

    result = await service.check_capability(plan.id)
    assert not result.ok
    assert "not approved" in result.error

    updated_plan = await repo.get_publication_plan_by_id(plan.id)
    assert updated_plan.status == "failed"


async def test_full_publish_lifecycle_succeeds_and_reconciles(db_session: AsyncSession) -> None:
    ctx = await _seed_workspace(db_session)
    item_id = await _seed_approved_text_item(db_session, ctx)

    platform_adapter = FakeSocialPlatform()
    service = _service(db_session, platform_adapter=platform_adapter)
    connection = await service.connect_platform(
        organization_id=ctx["organization_id"], workspace_id=ctx["workspace_id"], user_id=ctx["user_id"],
        platform="facebook", code="fake-code",
    )

    repo = PublishingRepository(db_session)
    plan = await repo.create_publication_plan(
        organization_id=ctx["organization_id"], workspace_id=ctx["workspace_id"], content_item_id=item_id,
        platform_connection_id=connection.id, created_by_user_id=ctx["user_id"], scheduled_for=None,
    )
    await db_session.commit()

    assert (await service.check_capability(plan.id)).ok
    await service.mark_approved(plan.id, ctx["user_id"])

    dispatch_result = await service.dispatch_publish(plan.id)
    assert dispatch_result.ok
    assert len(platform_adapter.published_calls) == 1
    assert platform_adapter.published_calls[0]["kind"] == "text"

    reconcile_result = await service.reconcile(plan.id, uuid.UUID(dispatch_result.attempt_id))
    assert reconcile_result.matches_expected
    assert reconcile_result.external_status == "published"

    updated_plan = await repo.get_publication_plan_by_id(plan.id)
    assert updated_plan.status == "published"
    assert updated_plan.approved_by_user_id == ctx["user_id"]

    attempts = await repo.list_attempts_for_plan(plan.id)
    assert len(attempts) == 1
    assert attempts[0].status == "succeeded"
    assert attempts[0].external_post_id is not None

    reconciliations = await repo.list_reconciliations_for_attempt(attempts[0].id)
    assert len(reconciliations) == 1
    assert reconciliations[0].matches_expected


async def test_dispatch_failure_marks_plan_failed(db_session: AsyncSession) -> None:
    ctx = await _seed_workspace(db_session)
    item_id = await _seed_approved_text_item(db_session, ctx)

    platform_adapter = FakeSocialPlatform(publish_should_fail=True)
    service = _service(db_session, platform_adapter=platform_adapter)
    connection = await service.connect_platform(
        organization_id=ctx["organization_id"], workspace_id=ctx["workspace_id"], user_id=ctx["user_id"],
        platform="facebook", code="fake-code",
    )

    repo = PublishingRepository(db_session)
    plan = await repo.create_publication_plan(
        organization_id=ctx["organization_id"], workspace_id=ctx["workspace_id"], content_item_id=item_id,
        platform_connection_id=connection.id, created_by_user_id=ctx["user_id"], scheduled_for=None,
    )
    await db_session.commit()
    await service.check_capability(plan.id)
    await service.mark_approved(plan.id, ctx["user_id"])

    dispatch_result = await service.dispatch_publish(plan.id)
    assert not dispatch_result.ok

    updated_plan = await repo.get_publication_plan_by_id(plan.id)
    assert updated_plan.status == "failed"

    attempts = await repo.list_attempts_for_plan(plan.id)
    assert attempts[0].status == "failed"


async def test_reconciliation_mismatch_marks_plan_failed(db_session: AsyncSession) -> None:
    ctx = await _seed_workspace(db_session)
    item_id = await _seed_approved_text_item(db_session, ctx)

    platform_adapter = FakeSocialPlatform(post_status="removed")
    service = _service(db_session, platform_adapter=platform_adapter)
    connection = await service.connect_platform(
        organization_id=ctx["organization_id"], workspace_id=ctx["workspace_id"], user_id=ctx["user_id"],
        platform="facebook", code="fake-code",
    )
    repo = PublishingRepository(db_session)
    plan = await repo.create_publication_plan(
        organization_id=ctx["organization_id"], workspace_id=ctx["workspace_id"], content_item_id=item_id,
        platform_connection_id=connection.id, created_by_user_id=ctx["user_id"], scheduled_for=None,
    )
    await db_session.commit()
    await service.check_capability(plan.id)
    await service.mark_approved(plan.id, ctx["user_id"])
    dispatch_result = await service.dispatch_publish(plan.id)

    reconcile_result = await service.reconcile(plan.id, uuid.UUID(dispatch_result.attempt_id))
    assert not reconcile_result.matches_expected

    updated_plan = await repo.get_publication_plan_by_id(plan.id)
    assert updated_plan.status == "failed"


async def test_finalize_rejected_does_not_publish(db_session: AsyncSession) -> None:
    ctx = await _seed_workspace(db_session)
    item_id = await _seed_approved_text_item(db_session, ctx)

    platform_adapter = FakeSocialPlatform()
    service = _service(db_session, platform_adapter=platform_adapter)
    connection = await service.connect_platform(
        organization_id=ctx["organization_id"], workspace_id=ctx["workspace_id"], user_id=ctx["user_id"],
        platform="facebook", code="fake-code",
    )
    repo = PublishingRepository(db_session)
    plan = await repo.create_publication_plan(
        organization_id=ctx["organization_id"], workspace_id=ctx["workspace_id"], content_item_id=item_id,
        platform_connection_id=connection.id, created_by_user_id=ctx["user_id"], scheduled_for=None,
    )
    await db_session.commit()
    await service.check_capability(plan.id)

    await service.finalize_rejected(plan.id, ctx["user_id"], "not the right time")

    updated_plan = await repo.get_publication_plan_by_id(plan.id)
    assert updated_plan.status == "rejected"
    assert updated_plan.failure_reason == "not the right time"
    assert len(platform_adapter.published_calls) == 0


async def test_delete_publication_plan_deletes_the_live_post_before_the_local_record(
    db_session: AsyncSession,
) -> None:
    ctx = await _seed_workspace(db_session)
    item_id = await _seed_approved_text_item(db_session, ctx)

    platform_adapter = FakeSocialPlatform()
    service = _service(db_session, platform_adapter=platform_adapter)
    connection = await service.connect_platform(
        organization_id=ctx["organization_id"], workspace_id=ctx["workspace_id"], user_id=ctx["user_id"],
        platform="facebook", code="fake-code",
    )
    repo = PublishingRepository(db_session)
    plan = await repo.create_publication_plan(
        organization_id=ctx["organization_id"], workspace_id=ctx["workspace_id"], content_item_id=item_id,
        platform_connection_id=connection.id, created_by_user_id=ctx["user_id"], scheduled_for=None,
    )
    await db_session.commit()
    await service.check_capability(plan.id)
    await service.mark_approved(plan.id, ctx["user_id"])
    dispatch_result = await service.dispatch_publish(plan.id)
    assert dispatch_result.ok
    attempts = await repo.list_attempts_for_plan(plan.id)
    real_post_id = attempts[0].external_post_id

    await service.delete_publication_plan(plan.id, ctx["user_id"])

    assert platform_adapter.deleted_post_ids == [real_post_id]
    assert await repo.get_publication_plan_by_id(plan.id) is None


async def test_delete_publication_plan_that_never_published_skips_the_platform_call(
    db_session: AsyncSession,
) -> None:
    ctx = await _seed_workspace(db_session)
    item_id = await _seed_approved_text_item(db_session, ctx)

    platform_adapter = FakeSocialPlatform()
    service = _service(db_session, platform_adapter=platform_adapter)
    connection = await service.connect_platform(
        organization_id=ctx["organization_id"], workspace_id=ctx["workspace_id"], user_id=ctx["user_id"],
        platform="facebook", code="fake-code",
    )
    repo = PublishingRepository(db_session)
    plan = await repo.create_publication_plan(
        organization_id=ctx["organization_id"], workspace_id=ctx["workspace_id"], content_item_id=item_id,
        platform_connection_id=connection.id, created_by_user_id=ctx["user_id"], scheduled_for=None,
    )
    await db_session.commit()

    await service.delete_publication_plan(plan.id, ctx["user_id"])

    assert platform_adapter.deleted_post_ids == []
    assert await repo.get_publication_plan_by_id(plan.id) is None


async def test_delete_publication_plan_keeps_the_local_record_when_the_platform_call_fails(
    db_session: AsyncSession,
) -> None:
    ctx = await _seed_workspace(db_session)
    item_id = await _seed_approved_text_item(db_session, ctx)

    platform_adapter = FakeSocialPlatform()
    service = _service(db_session, platform_adapter=platform_adapter)
    connection = await service.connect_platform(
        organization_id=ctx["organization_id"], workspace_id=ctx["workspace_id"], user_id=ctx["user_id"],
        platform="facebook", code="fake-code",
    )
    repo = PublishingRepository(db_session)
    plan = await repo.create_publication_plan(
        organization_id=ctx["organization_id"], workspace_id=ctx["workspace_id"], content_item_id=item_id,
        platform_connection_id=connection.id, created_by_user_id=ctx["user_id"], scheduled_for=None,
    )
    await db_session.commit()
    await service.check_capability(plan.id)
    await service.mark_approved(plan.id, ctx["user_id"])
    await service.dispatch_publish(plan.id)

    platform_adapter.delete_should_fail = True
    with pytest.raises(RuntimeError, match="simulated platform delete failure"):
        await service.delete_publication_plan(plan.id, ctx["user_id"])

    # Never leave the app's tracking gone while the real post is still live.
    assert await repo.get_publication_plan_by_id(plan.id) is not None


async def test_delete_publication_plan_wraps_a_platform_rejection_as_a_named_exception(
    db_session: AsyncSession,
) -> None:
    """A platform-side rejection of the delete (e.g. a missing permission
    scope) needs to be a distinct, actionable failure the API layer can
    tell apart from a generic/transient error, not a bare httpx exception
    bubbling up as an unhandled 500. Uses facebook — instagram is
    deliberately excluded from ever attempting the platform call at all
    (see test_delete_publication_plan_skips_the_platform_call_for_instagram),
    so it can't exercise this path."""
    ctx = await _seed_workspace(db_session)
    item_id = await _seed_approved_text_item(db_session, ctx)

    platform_adapter = FakeSocialPlatform()
    service = _service(db_session, platform_adapter=platform_adapter)
    connection = await service.connect_platform(
        organization_id=ctx["organization_id"], workspace_id=ctx["workspace_id"], user_id=ctx["user_id"],
        platform="facebook", code="fake-code",
    )
    repo = PublishingRepository(db_session)
    plan = await repo.create_publication_plan(
        organization_id=ctx["organization_id"], workspace_id=ctx["workspace_id"], content_item_id=item_id,
        platform_connection_id=connection.id, created_by_user_id=ctx["user_id"], scheduled_for=None,
    )
    await db_session.commit()
    await service.check_capability(plan.id)
    await service.mark_approved(plan.id, ctx["user_id"])
    await service.dispatch_publish(plan.id)

    platform_adapter.delete_should_fail_with_platform_error = True
    with pytest.raises(PlatformDeleteRejected) as exc_info:
        await service.delete_publication_plan(plan.id, ctx["user_id"])
    assert exc_info.value.platform == "facebook"

    assert await repo.get_publication_plan_by_id(plan.id) is not None


async def test_delete_publication_plan_skips_the_platform_call_for_instagram(db_session: AsyncSession) -> None:
    """Regression test for a real production failure (ceri.gr): Instagram
    delete 400s with "does not support this operation" — turned out to be
    a missing permission scope this app's OAuth product config can't
    actually grant (requesting it 400s the login dialog itself). Until
    that's sorted out, deleting an Instagram plan must never attempt the
    real platform call — app-record-only, matching how Facebook cleanup
    was handled manually earlier — and must still succeed regardless of
    what the platform adapter would have done."""
    ctx = await _seed_workspace(db_session)
    item_id = await _seed_approved_text_item(db_session, ctx)

    platform_adapter = FakeSocialPlatform()
    platform_adapter.delete_should_fail_with_platform_error = True  # would raise if ever called
    service = _service(db_session, platform_adapter=platform_adapter)
    connection = await service.connect_platform(
        organization_id=ctx["organization_id"], workspace_id=ctx["workspace_id"], user_id=ctx["user_id"],
        platform="instagram", code="fake-code",
    )
    repo = PublishingRepository(db_session)
    plan = await repo.create_publication_plan(
        organization_id=ctx["organization_id"], workspace_id=ctx["workspace_id"], content_item_id=item_id,
        platform_connection_id=connection.id, created_by_user_id=ctx["user_id"], scheduled_for=None,
    )
    await db_session.commit()
    await service.check_capability(plan.id)
    await service.mark_approved(plan.id, ctx["user_id"])
    await service.dispatch_publish(plan.id)

    await service.delete_publication_plan(plan.id, ctx["user_id"])

    assert platform_adapter.deleted_post_ids == []
    assert await repo.get_publication_plan_by_id(plan.id) is None
