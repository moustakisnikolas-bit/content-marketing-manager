import uuid
from dataclasses import dataclass
from datetime import timedelta

from temporalio import activity, workflow
from temporalio.common import RetryPolicy

# Phase 4's Auto-Pilot workflow — the genuinely new automation pattern this
# phase introduces (Manual/Guided modes just orchestrate the existing
# Phase 2/3 workflows directly from the API, no new workflow type needed).
# Every item re-checks OPA guardrails against live data immediately before
# it runs, so a kill switch flipped in the AutoPilotPolicy table is caught
# on the next item automatically — the explicit `halt` signal below is a
# faster, more immediate stop on top of that, per the spec's requirement
# that a kill switch "halts in-flight and future runs."


@dataclass
class AutoPilotWorkflowInput:
    campaign_id: str
    plan_item_ids: list[str]


async def _build_autopilot_service():
    from content_studio.adapters.factory import (
        get_ai_image_adapter,
        get_ai_text_adapter,
        get_policy_adapter,
        get_secrets_adapter,
        get_social_platform_adapter,
    )
    from content_studio.adapters.object_storage.seaweedfs import SeaweedFSObjectStorage
    from content_studio.config import get_settings
    from content_studio.db.session import SessionLocal
    from content_studio.modules.marketing.autopilot_service import AutoPilotService

    settings = get_settings()
    session = SessionLocal()
    # Auto-Pilot items always propose a specific target_platform up front
    # (see proposal_generator.py), and which connection actually gets
    # matched (and thus which real platform adapter is needed) isn't known
    # until run_item() resolves it — so a factory, resolved per item against
    # the connection's actual platform, not a single adapter built here.
    service = AutoPilotService(
        session,
        policy=get_policy_adapter(settings),
        ai_text=get_ai_text_adapter(settings),
        ai_image=get_ai_image_adapter(settings),
        object_storage=SeaweedFSObjectStorage(settings),
        secrets=get_secrets_adapter(settings),
        platform_adapter_factory=lambda platform: get_social_platform_adapter(settings, platform),
    )
    return session, service


@activity.defn
async def run_autopilot_item_activity(campaign_id: str, plan_item_id: str) -> dict:
    session, service = await _build_autopilot_service()
    async with session:
        result = await service.run_item(uuid.UUID(campaign_id), uuid.UUID(plan_item_id))
        return {"proceeded": result.proceeded, "published": result.published, "reasons": result.reasons}


@activity.defn
async def mark_item_cancelled_activity(plan_item_id: str) -> None:
    from content_studio.db.session import SessionLocal
    from content_studio.modules.marketing.repository import MarketingRepository

    async with SessionLocal() as session:
        repo = MarketingRepository(session)
        item = await repo.get_plan_item_by_id(uuid.UUID(plan_item_id))
        assert item is not None
        await repo.update_plan_item_status(item, "cancelled")
        await session.commit()


_STANDARD_RETRY = RetryPolicy(maximum_attempts=1)


@workflow.defn
class AutoPilotCampaignWorkflow:
    def __init__(self) -> None:
        self._halted = False

    @workflow.run
    async def run(self, input: AutoPilotWorkflowInput) -> dict:
        item_results = []
        for plan_item_id in input.plan_item_ids:
            if self._halted:
                await workflow.execute_activity(
                    mark_item_cancelled_activity,
                    plan_item_id,
                    start_to_close_timeout=timedelta(seconds=15),
                    retry_policy=_STANDARD_RETRY,
                )
                item_results.append({"plan_item_id": plan_item_id, "cancelled": True})
                continue

            result = await workflow.execute_activity(
                run_autopilot_item_activity,
                args=[input.campaign_id, plan_item_id],
                start_to_close_timeout=timedelta(seconds=120),
                retry_policy=_STANDARD_RETRY,
            )
            item_results.append({"plan_item_id": plan_item_id, **result})

        return {"halted": self._halted, "items": item_results}

    @workflow.signal
    def halt(self) -> None:
        self._halted = True
