import uuid
from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession

from content_studio.modules.creation.repository import CreationRepository
from content_studio.modules.governance.service import AuditService
from content_studio.modules.marketing.exceptions import (
    BriefNotFound,
    GoalNotFound,
    NoActiveRecipe,
    ProposalNotFound,
)
from content_studio.modules.marketing.models import (
    Campaign,
    CampaignPlanItem,
    CampaignProposal,
    MarketingBrief,
)
from content_studio.modules.marketing.proposal_generator import generate_proposal_draft
from content_studio.modules.marketing.repository import MarketingRepository


@dataclass(frozen=True)
class PreparedGeneration:
    content_item_id: uuid.UUID
    recipe_id: uuid.UUID
    brief_text: str
    reference_image_url: str | None = None


# GenerationJob.status -> the CampaignPlanItem-level status it implies,
# for get_effective_plan_item_statuses(). "generating"/"pending" job
# statuses aren't mapped here — they imply no change from what's already
# stored. "approved" is a response-only value: it's not one of
# PLAN_ITEM_STATUSES (never written to the DB column, so no CHECK
# constraint conflict), it only ever appears as this computed overlay —
# used by the frontend to sort approved-but-not-yet-published items to the
# end of a campaign's item list.
_JOB_STATUS_TO_EFFECTIVE_PLAN_ITEM_STATUS = {
    "awaiting_review": "awaiting_review",
    "approved": "approved",
    "quality_gate_failed": "failed",
    "rejected": "failed",
    "failed": "failed",
}


class MarketingService:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self._repo = MarketingRepository(session)
        self._creation_repo = CreationRepository(session)
        self._audit = AuditService(session)

    async def create_brief(
        self,
        *,
        organization_id: uuid.UUID,
        workspace_id: uuid.UUID,
        user_id: uuid.UUID,
        goal_slug: str,
        what_to_promote: str,
        mode: str,
        target_platforms: list[str],
    ) -> MarketingBrief:
        goal = await self._repo.get_goal_by_slug(goal_slug)
        if goal is None:
            raise GoalNotFound(goal_slug)

        brief = await self._repo.create_brief(
            organization_id=organization_id,
            workspace_id=workspace_id,
            created_by_user_id=user_id,
            goal_id=goal.id,
            what_to_promote=what_to_promote,
            mode=mode,
            target_platforms=target_platforms,
        )
        await self._session.commit()
        return brief

    async def generate_proposal(self, brief_id: uuid.UUID) -> CampaignProposal:
        brief = await self._repo.get_brief_by_id(brief_id)
        if brief is None:
            raise BriefNotFound(str(brief_id))
        goal = await self._repo.get_goal_by_id(brief.goal_id)
        assert goal is not None

        recipe = await self._creation_repo.get_active_recipe_for_content_type("text")
        if recipe is None:
            raise NoActiveRecipe("text")

        draft = generate_proposal_draft(
            goal_label=goal.label,
            goal_slug=goal.slug,
            what_to_promote=brief.what_to_promote,
            target_platforms=brief.target_platforms,
            per_item_estimated_cost=recipe.estimated_cost,
        )

        proposal = await self._repo.create_proposal(
            brief_id=brief.id,
            objective=draft.objective,
            assumptions=draft.assumptions,
            plan_summary=draft.plan_summary,
            estimated_cost=draft.estimated_cost,
            explanation=draft.explanation,
        )
        proposal.plan_items_draft = [
            {"title": i.title, "brief_text": i.brief_text, "platform": i.platform} for i in draft.plan_items
        ]
        await self._session.commit()
        return proposal

    async def approve_proposal(
        self, *, proposal_id: uuid.UUID, user_id: uuid.UUID, campaign_name: str
    ) -> Campaign:
        proposal = await self._repo.get_proposal_by_id(proposal_id)
        if proposal is None:
            raise ProposalNotFound(str(proposal_id))
        brief = await self._repo.get_brief_by_id(proposal.brief_id)
        assert brief is not None

        campaign = await self._repo.create_campaign(
            organization_id=brief.organization_id,
            workspace_id=brief.workspace_id,
            proposal_id=proposal.id,
            approved_by_user_id=user_id,
            name=campaign_name,
        )

        for index, raw_item in enumerate(proposal.plan_items_draft, start=1):
            await self._repo.create_plan_item(
                campaign_id=campaign.id,
                sequence_number=index,
                title=raw_item["title"],
                brief_text=raw_item["brief_text"],
                target_platform=raw_item.get("platform"),
            )

        await self._repo.update_proposal_status(proposal, "approved")
        await self._repo.create_decision(
            campaign_id=campaign.id,
            decision_type="proposal_generated",
            explanation=proposal.explanation,
        )
        await self._audit.record(
            event_type="marketing.campaign_approved",
            actor_type="user",
            actor_id=str(user_id),
            organization_id=brief.organization_id,
            summary=f"Approved campaign '{campaign_name}' with {len(proposal.plan_items_draft)} planned item(s)",
            payload={"campaign_id": str(campaign.id), "proposal_id": str(proposal.id)},
        )
        await self._session.commit()
        return campaign

    async def prepare_item_generation(
        self, plan_item: CampaignPlanItem, *, reference_image_url: str | None = None
    ) -> PreparedGeneration:
        """Creates the Phase 2 ContentItem for this plan item (but not the
        GenerationJob/workflow — that needs the Temporal client, which
        lives at the API/activity layer, not here)."""
        campaign = await self._repo.get_campaign_by_id(plan_item.campaign_id)
        assert campaign is not None
        recipe = await self._creation_repo.get_active_recipe_for_content_type(plan_item.content_type)
        if recipe is None:
            raise NoActiveRecipe(plan_item.content_type)

        content_item = await self._creation_repo.create_content_item(
            organization_id=campaign.organization_id,
            workspace_id=campaign.workspace_id,
            created_by_user_id=campaign.approved_by_user_id,
            content_type=plan_item.content_type,
            title=plan_item.title,
        )
        await self._session.commit()
        return PreparedGeneration(
            content_item_id=content_item.id, recipe_id=recipe.id, brief_text=plan_item.brief_text,
            reference_image_url=reference_image_url,
        )

    async def get_effective_plan_item_statuses(self, items: list[CampaignPlanItem]) -> dict[uuid.UUID, str]:
        """Maps each item's *effective* status, reading through to its
        linked GenerationJob for items still stored as "generating" —
        that's written once at dispatch time and never updated again by
        the Guided/bulk dispatch path; only Auto-Pilot's own code path
        (autopilot_service.py) keeps it in sync as work progresses. So a
        "generating" item can genuinely be done already. Returns
        {item_id: status} for every item, including unchanged ones, so
        callers don't need to special-case "was it overridden." """
        stale_job_ids = [i.generation_job_id for i in items if i.status == "generating" and i.generation_job_id]
        jobs_by_id = {}
        if stale_job_ids:
            jobs = await self._creation_repo.get_generation_jobs_by_ids(stale_job_ids)
            jobs_by_id = {j.id: j for j in jobs}

        result: dict[uuid.UUID, str] = {}
        for item in items:
            job = jobs_by_id.get(item.generation_job_id) if item.status == "generating" else None
            result[item.id] = _JOB_STATUS_TO_EFFECTIVE_PLAN_ITEM_STATUS.get(job.status, item.status) if job else item.status
        return result
