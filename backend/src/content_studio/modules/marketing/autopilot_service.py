import uuid
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy.ext.asyncio import AsyncSession

from content_studio.modules.billing.repository import BillingRepository
from content_studio.modules.creation.generation_service import GenerationService
from content_studio.modules.creation.repository import CreationRepository
from content_studio.modules.governance.service import AuditService
from content_studio.modules.marketing.repository import MarketingRepository
from content_studio.modules.publishing.repository import PublishingRepository
from content_studio.modules.publishing.service import PublishingService
from content_studio.ports.ai_image import AIImagePort
from content_studio.ports.ai_text import AITextPort
from content_studio.ports.object_storage import ObjectStoragePort
from content_studio.ports.policy import PolicyPort
from content_studio.ports.secrets import SecretsPort
from content_studio.ports.social_platform import SocialPlatformPort

_AUTOPILOT_POLICY_PATH = "content_studio.autopilot"


@dataclass(frozen=True)
class ItemResult:
    proceeded: bool
    published: bool
    reasons: list[str]


class AutoPilotService:
    """Runs one campaign plan item through the fully-autonomous path:
    OPA guardrail check -> generate -> quality gate -> auto-approve ->
    publish -> reconcile. Reuses GenerationService and PublishingService
    directly rather than the human-review-gated GenerationWorkflow/
    PublicationWorkflow — bounded autonomy means the *policy* stands in
    for the human approval, not that approval is skipped entirely."""

    def __init__(
        self,
        session: AsyncSession,
        *,
        policy: PolicyPort,
        ai_text: AITextPort,
        ai_image: AIImagePort,
        object_storage: ObjectStoragePort,
        secrets: SecretsPort,
        platform_adapter_factory: Callable[[str], SocialPlatformPort],
    ) -> None:
        self._session = session
        self._repo = MarketingRepository(session)
        self._creation_repo = CreationRepository(session)
        self._publishing_repo = PublishingRepository(session)
        self._billing_repo = BillingRepository(session)
        self._audit = AuditService(session)
        self._policy = policy
        self._ai_text = ai_text
        self._ai_image = ai_image
        self._object_storage = object_storage
        self._secrets = secrets
        self._platform_adapter_factory = platform_adapter_factory

    async def check_guardrails(self, campaign_id: uuid.UUID, plan_item_id: uuid.UUID) -> tuple[bool, list[str]]:
        campaign = await self._repo.get_campaign_by_id(campaign_id)
        assert campaign is not None
        autopilot_policy = await self._repo.get_autopilot_policy_for_campaign(campaign_id)
        assert autopilot_policy is not None
        plan_item = await self._repo.get_plan_item_by_id(plan_item_id)
        assert plan_item is not None
        recipe = await self._creation_repo.get_active_recipe_for_content_type("text")
        assert recipe is not None

        now = datetime.now(UTC)
        input_data = {
            "platform": plan_item.target_platform or "",
            "allowed_platforms": autopilot_policy.allowed_platforms,
            "spend_used": str(campaign.total_spent),
            "estimated_next_cost": str(recipe.estimated_cost),
            "spend_limit": str(autopilot_policy.max_total_spend),
            "current_hour": now.hour,
            "window_start_hour": autopilot_policy.posting_window_start_hour,
            "window_end_hour": autopilot_policy.posting_window_end_hour,
            "blocked_topics": autopilot_policy.blocked_topics,
            "topic_text": plan_item.brief_text,
            "kill_switch_active": autopilot_policy.kill_switch_active,
        }
        result = await self._policy.evaluate(policy_path=_AUTOPILOT_POLICY_PATH, input_data=input_data)
        return bool(result.get("allow", False)), list(result.get("deny_reasons", []))

    async def run_item(self, campaign_id: uuid.UUID, plan_item_id: uuid.UUID) -> ItemResult:
        campaign = await self._repo.get_campaign_by_id(campaign_id)
        assert campaign is not None
        plan_item = await self._repo.get_plan_item_by_id(plan_item_id)
        assert plan_item is not None

        allow, reasons = await self.check_guardrails(campaign_id, plan_item_id)
        if not allow:
            await self._repo.update_plan_item_status(plan_item, "skipped")
            await self._repo.create_decision(
                campaign_id=campaign_id,
                plan_item_id=plan_item_id,
                decision_type="autopilot_skipped",
                explanation="Skipped this item because: " + "; ".join(reasons),
            )
            await self._session.commit()
            return ItemResult(proceeded=False, published=False, reasons=reasons)

        await self._repo.create_decision(
            campaign_id=campaign_id,
            plan_item_id=plan_item_id,
            decision_type="autopilot_proceed",
            explanation=(
                "Proceeding: within the allowed platform, spend limit, posting window, "
                "and no blocked topics detected."
            ),
        )
        await self._repo.update_plan_item_status(plan_item, "generating")
        await self._session.commit()

        subscription = await self._billing_repo.get_subscription_for_organization(campaign.organization_id)
        assert subscription is not None
        recipe = await self._creation_repo.get_active_recipe_for_content_type("text")
        assert recipe is not None

        content_item = await self._creation_repo.create_content_item(
            organization_id=campaign.organization_id,
            workspace_id=campaign.workspace_id,
            created_by_user_id=campaign.approved_by_user_id,
            content_type="text",
            title=plan_item.title,
        )
        job = await self._creation_repo.create_generation_job(
            organization_id=campaign.organization_id,
            workspace_id=campaign.workspace_id,
            content_item_id=content_item.id,
            recipe_id=recipe.id,
            requested_by_user_id=campaign.approved_by_user_id,
            subscription_id=subscription.id,
            brief_text=plan_item.brief_text,
        )
        await self._repo.link_plan_item_generation(plan_item, content_item_id=content_item.id, generation_job_id=job.id)
        await self._session.commit()

        gen_service = GenerationService(
            self._session, ai_text=self._ai_text, ai_image=self._ai_image, object_storage=self._object_storage
        )
        reserve_result = await gen_service.reserve_cost(job.id)
        if not reserve_result.ok:
            await self._repo.update_plan_item_status(plan_item, "failed")
            await self._repo.create_decision(
                campaign_id=campaign_id, plan_item_id=plan_item_id, decision_type="autopilot_skipped",
                explanation=f"Could not reserve budget: {reserve_result.error}",
            )
            await self._session.commit()
            return ItemResult(proceeded=True, published=False, reasons=[reserve_result.error or "reservation failed"])

        dispatch_result = await gen_service.dispatch(job.id)
        if not dispatch_result.ok:
            await self._repo.update_plan_item_status(plan_item, "failed")
            await self._session.commit()
            return ItemResult(proceeded=True, published=False, reasons=[dispatch_result.error or "generation failed"])

        await self._repo.add_campaign_spend(campaign, recipe.estimated_cost)

        gate_result = await gen_service.run_quality_gate(job.id, uuid.UUID(dispatch_result.revision_id))
        if not gate_result.passed:
            await self._repo.update_plan_item_status(plan_item, "failed")
            await self._repo.create_decision(
                campaign_id=campaign_id, plan_item_id=plan_item_id, decision_type="autopilot_skipped",
                explanation="Generated content failed the brand quality gate: " + "; ".join(gate_result.violations),
            )
            await self._session.commit()
            return ItemResult(proceeded=True, published=False, reasons=gate_result.violations)

        # Auto-Pilot auto-approves in the campaign creator's name — this is
        # the bounded-autonomy substitute for a human review, gated by the
        # OPA guardrail check that already ran above, not a bypass of it.
        await gen_service.finalize_approved(
            job.id, uuid.UUID(dispatch_result.revision_id), campaign.approved_by_user_id, "Auto-approved by Auto-Pilot"
        )
        await self._repo.update_plan_item_status(plan_item, "awaiting_review")
        await self._session.commit()

        if not plan_item.target_platform:
            await self._repo.update_plan_item_status(plan_item, "published")
            await self._session.commit()
            return ItemResult(proceeded=True, published=False, reasons=["no target platform — content approved but not published"])

        connections = await self._publishing_repo.list_connections_for_workspace(campaign.workspace_id)
        connection = next((c for c in connections if c.platform == plan_item.target_platform), None)
        if connection is None:
            await self._repo.update_plan_item_status(plan_item, "published")
            await self._session.commit()
            return ItemResult(
                proceeded=True, published=False,
                reasons=[f"no connected {plan_item.target_platform} account — content approved but not published"],
            )

        pub_service = PublishingService(
            self._session,
            platform_adapter=self._platform_adapter_factory(connection.platform),
            secrets=self._secrets,
            object_storage=self._object_storage,
        )
        pub_plan = await self._publishing_repo.create_publication_plan(
            organization_id=campaign.organization_id, workspace_id=campaign.workspace_id,
            content_item_id=content_item.id, platform_connection_id=connection.id,
            created_by_user_id=campaign.approved_by_user_id, scheduled_for=None,
        )
        await self._repo.link_plan_item_publication(plan_item, publication_plan_id=pub_plan.id)
        await self._repo.set_plan_item_connection(plan_item, connection.id)
        await self._session.commit()

        capability_result = await pub_service.check_capability(pub_plan.id)
        if not capability_result.ok:
            await self._repo.update_plan_item_status(plan_item, "failed")
            await self._session.commit()
            return ItemResult(proceeded=True, published=False, reasons=[capability_result.error or "capability unavailable"])

        await pub_service.mark_approved(pub_plan.id, campaign.approved_by_user_id)
        dispatch = await pub_service.dispatch_publish(pub_plan.id)
        if not dispatch.ok:
            await self._repo.update_plan_item_status(plan_item, "failed")
            await self._session.commit()
            return ItemResult(proceeded=True, published=False, reasons=[dispatch.error or "publish failed"])

        await pub_service.reconcile(pub_plan.id, uuid.UUID(dispatch.attempt_id))
        await self._repo.update_plan_item_status(plan_item, "published")
        await self._audit.record(
            event_type="marketing.autopilot_published",
            actor_type="service",
            organization_id=campaign.organization_id,
            summary=f"Auto-Pilot published '{plan_item.title}' to {plan_item.target_platform}",
            payload={"campaign_id": str(campaign_id), "plan_item_id": str(plan_item_id)},
        )
        await self._session.commit()
        return ItemResult(proceeded=True, published=True, reasons=[])
