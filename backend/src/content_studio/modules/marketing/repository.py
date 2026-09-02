import uuid
from datetime import UTC, datetime
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from content_studio.modules.marketing.models import (
    AutoPilotPolicy,
    Campaign,
    CampaignDecision,
    CampaignPlanItem,
    CampaignProposal,
    MarketingBrief,
    MarketingGoal,
)


class MarketingRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    # -- Goals ------------------------------------------------------------

    async def list_goals(self) -> list[MarketingGoal]:
        result = await self._session.execute(select(MarketingGoal).order_by(MarketingGoal.label))
        return list(result.scalars().all())

    async def get_goal_by_slug(self, slug: str) -> MarketingGoal | None:
        result = await self._session.execute(select(MarketingGoal).where(MarketingGoal.slug == slug))
        return result.scalar_one_or_none()

    async def get_goal_by_id(self, goal_id: uuid.UUID) -> MarketingGoal | None:
        return await self._session.get(MarketingGoal, goal_id)

    async def create_goal(self, *, slug: str, label: str, description: str) -> MarketingGoal:
        goal = MarketingGoal(slug=slug, label=label, description=description)
        self._session.add(goal)
        await self._session.flush()
        return goal

    # -- Briefs ------------------------------------------------------------

    async def create_brief(
        self,
        *,
        organization_id: uuid.UUID,
        workspace_id: uuid.UUID,
        created_by_user_id: uuid.UUID,
        goal_id: uuid.UUID,
        what_to_promote: str,
        mode: str,
        target_platforms: list[str],
    ) -> MarketingBrief:
        brief = MarketingBrief(
            organization_id=organization_id,
            workspace_id=workspace_id,
            created_by_user_id=created_by_user_id,
            goal_id=goal_id,
            what_to_promote=what_to_promote,
            mode=mode,
            target_platforms=target_platforms,
        )
        self._session.add(brief)
        await self._session.flush()
        return brief

    async def get_brief_by_id(self, brief_id: uuid.UUID) -> MarketingBrief | None:
        return await self._session.get(MarketingBrief, brief_id)

    # -- Proposals ------------------------------------------------------------

    async def create_proposal(
        self,
        *,
        brief_id: uuid.UUID,
        objective: str,
        assumptions: list[str],
        plan_summary: str,
        estimated_cost: Decimal,
        explanation: str,
    ) -> CampaignProposal:
        proposal = CampaignProposal(
            brief_id=brief_id,
            objective=objective,
            assumptions=assumptions,
            plan_summary=plan_summary,
            estimated_cost=estimated_cost,
            explanation=explanation,
        )
        self._session.add(proposal)
        await self._session.flush()
        return proposal

    async def get_proposal_by_id(self, proposal_id: uuid.UUID) -> CampaignProposal | None:
        return await self._session.get(CampaignProposal, proposal_id)

    async def update_proposal_status(self, proposal: CampaignProposal, status: str) -> None:
        proposal.status = status
        await self._session.flush()

    # -- Campaigns ------------------------------------------------------------

    async def create_campaign(
        self,
        *,
        organization_id: uuid.UUID,
        workspace_id: uuid.UUID,
        proposal_id: uuid.UUID,
        approved_by_user_id: uuid.UUID,
        name: str,
    ) -> Campaign:
        campaign = Campaign(
            organization_id=organization_id,
            workspace_id=workspace_id,
            proposal_id=proposal_id,
            approved_by_user_id=approved_by_user_id,
            name=name,
        )
        self._session.add(campaign)
        await self._session.flush()
        return campaign

    async def get_campaign_by_id(self, campaign_id: uuid.UUID) -> Campaign | None:
        return await self._session.get(Campaign, campaign_id)

    async def list_campaigns_for_workspace(self, workspace_id: uuid.UUID) -> list[Campaign]:
        result = await self._session.execute(
            select(Campaign).where(Campaign.workspace_id == workspace_id).order_by(Campaign.created_at.desc())
        )
        return list(result.scalars().all())

    async def set_campaign_workflow_id(self, campaign: Campaign, workflow_id: str) -> None:
        campaign.temporal_workflow_id = workflow_id
        await self._session.flush()

    async def update_campaign_status(self, campaign: Campaign, status: str) -> None:
        campaign.status = status
        await self._session.flush()

    async def add_campaign_spend(self, campaign: Campaign, amount: Decimal) -> None:
        campaign.total_spent += amount
        await self._session.flush()

    # -- Plan items ------------------------------------------------------------

    async def create_plan_item(
        self,
        *,
        campaign_id: uuid.UUID,
        sequence_number: int,
        title: str,
        brief_text: str,
        target_platform: str | None = None,
        platform_connection_id: uuid.UUID | None = None,
        product_id: uuid.UUID | None = None,
        content_type: str = "text",
        source_plan_item_id: uuid.UUID | None = None,
    ) -> CampaignPlanItem:
        item = CampaignPlanItem(
            campaign_id=campaign_id,
            sequence_number=sequence_number,
            title=title,
            brief_text=brief_text,
            target_platform=target_platform,
            platform_connection_id=platform_connection_id,
            product_id=product_id,
            content_type=content_type,
            source_plan_item_id=source_plan_item_id,
        )
        self._session.add(item)
        await self._session.flush()
        return item

    async def get_plan_item_by_id(self, item_id: uuid.UUID) -> CampaignPlanItem | None:
        return await self._session.get(CampaignPlanItem, item_id)

    async def get_plan_item_by_publication_plan_id(self, publication_plan_id: uuid.UUID) -> CampaignPlanItem | None:
        result = await self._session.execute(
            select(CampaignPlanItem).where(CampaignPlanItem.publication_plan_id == publication_plan_id)
        )
        return result.scalar_one_or_none()

    async def get_plan_item_by_generation_job_id(self, generation_job_id: uuid.UUID) -> CampaignPlanItem | None:
        result = await self._session.execute(
            select(CampaignPlanItem).where(CampaignPlanItem.generation_job_id == generation_job_id)
        )
        return result.scalar_one_or_none()

    async def get_plan_item_by_content_item_id(self, content_item_id: uuid.UUID) -> CampaignPlanItem | None:
        # content_item_id stays stable across regenerations (a new job
        # reuses the same content_item_id), unlike generation_job_id — the
        # right key to resolve "which plan item does this revision belong
        # to" regardless of how many regen rounds it's been through.
        result = await self._session.execute(
            select(CampaignPlanItem).where(CampaignPlanItem.content_item_id == content_item_id)
        )
        return result.scalar_one_or_none()

    async def list_plan_items_for_campaign(self, campaign_id: uuid.UUID) -> list[CampaignPlanItem]:
        result = await self._session.execute(
            select(CampaignPlanItem)
            .where(CampaignPlanItem.campaign_id == campaign_id)
            .order_by(CampaignPlanItem.sequence_number)
        )
        return list(result.scalars().all())

    async def update_plan_item_status(self, item: CampaignPlanItem, status: str) -> None:
        item.status = status
        await self._session.flush()

    async def update_plan_item_brief_text(self, item: CampaignPlanItem, brief_text: str) -> None:
        item.brief_text = brief_text
        await self._session.flush()

    async def set_plan_item_connection(self, item: CampaignPlanItem, connection_id: uuid.UUID) -> None:
        item.platform_connection_id = connection_id
        await self._session.flush()

    async def link_plan_item_generation(
        self, item: CampaignPlanItem, *, content_item_id: uuid.UUID, generation_job_id: uuid.UUID
    ) -> None:
        item.content_item_id = content_item_id
        item.generation_job_id = generation_job_id
        await self._session.flush()

    async def link_plan_item_publication(self, item: CampaignPlanItem, *, publication_plan_id: uuid.UUID) -> None:
        item.publication_plan_id = publication_plan_id
        await self._session.flush()

    # -- Decisions ------------------------------------------------------------

    async def create_decision(
        self,
        *,
        campaign_id: uuid.UUID,
        decision_type: str,
        explanation: str,
        plan_item_id: uuid.UUID | None = None,
    ) -> CampaignDecision:
        decision = CampaignDecision(
            campaign_id=campaign_id,
            plan_item_id=plan_item_id,
            decision_type=decision_type,
            explanation=explanation,
            created_at=datetime.now(UTC),
        )
        self._session.add(decision)
        await self._session.flush()
        return decision

    async def list_decisions_for_campaign(self, campaign_id: uuid.UUID) -> list[CampaignDecision]:
        result = await self._session.execute(
            select(CampaignDecision)
            .where(CampaignDecision.campaign_id == campaign_id)
            .order_by(CampaignDecision.created_at)
        )
        return list(result.scalars().all())

    # -- Auto-Pilot policy ------------------------------------------------------------

    async def create_autopilot_policy(
        self,
        *,
        campaign_id: uuid.UUID,
        created_by_user_id: uuid.UUID,
        allowed_platforms: list[str],
        max_total_spend: Decimal,
        blocked_topics: list[str],
        posting_window_start_hour: int,
        posting_window_end_hour: int,
    ) -> AutoPilotPolicy:
        policy = AutoPilotPolicy(
            campaign_id=campaign_id,
            created_by_user_id=created_by_user_id,
            allowed_platforms=allowed_platforms,
            max_total_spend=max_total_spend,
            blocked_topics=blocked_topics,
            posting_window_start_hour=posting_window_start_hour,
            posting_window_end_hour=posting_window_end_hour,
        )
        self._session.add(policy)
        await self._session.flush()
        return policy

    async def get_autopilot_policy_for_campaign(self, campaign_id: uuid.UUID) -> AutoPilotPolicy | None:
        result = await self._session.execute(
            select(AutoPilotPolicy).where(AutoPilotPolicy.campaign_id == campaign_id)
        )
        return result.scalar_one_or_none()

    async def set_kill_switch(self, policy: AutoPilotPolicy, active: bool) -> None:
        policy.kill_switch_active = active
        await self._session.flush()
