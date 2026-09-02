import uuid
from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, Field


class MarketingGoalOut(BaseModel):
    id: uuid.UUID
    slug: str
    label: str
    description: str

    model_config = {"from_attributes": True}


class CreateBriefRequest(BaseModel):
    goal_slug: str
    what_to_promote: str = Field(min_length=1, max_length=2000)
    mode: str = Field(pattern="^(manual|guided|autopilot)$")
    target_platforms: list[str] = Field(default_factory=list)


class CampaignProposalOut(BaseModel):
    id: uuid.UUID
    brief_id: uuid.UUID
    objective: str
    assumptions: list[str]
    plan_summary: str
    plan_items_draft: list[dict]
    estimated_cost: Decimal
    explanation: str
    status: str

    model_config = {"from_attributes": True}


class CreateBriefResponse(BaseModel):
    brief_id: uuid.UUID
    proposal: CampaignProposalOut


class ApproveProposalRequest(BaseModel):
    campaign_name: str = Field(min_length=1, max_length=300)


class ApproveProposalResponse(BaseModel):
    campaign_id: uuid.UUID


class CampaignPlanItemOut(BaseModel):
    id: uuid.UUID
    sequence_number: int
    title: str
    brief_text: str
    target_platform: str | None
    status: str
    content_item_id: uuid.UUID | None
    publication_plan_id: uuid.UUID | None
    generation_job_id: uuid.UUID | None
    product_id: uuid.UUID | None
    content_type: str

    model_config = {"from_attributes": True}


class CampaignOut(BaseModel):
    id: uuid.UUID
    name: str
    status: str
    total_spent: Decimal
    created_at: datetime

    model_config = {"from_attributes": True}


class CampaignDecisionOut(BaseModel):
    decision_type: str
    explanation: str
    created_at: datetime
    plan_item_id: uuid.UUID | None

    model_config = {"from_attributes": True}


class CampaignDetailOut(BaseModel):
    campaign: CampaignOut
    plan_items: list[CampaignPlanItemOut]
    decisions: list[CampaignDecisionOut]


class CreateAutoPilotPolicyRequest(BaseModel):
    allowed_platforms: list[str] = Field(default_factory=list)
    max_total_spend: Decimal
    blocked_topics: list[str] = Field(default_factory=list)
    posting_window_start_hour: int = Field(default=0, ge=0, le=23)
    posting_window_end_hour: int = Field(default=23, ge=0, le=23)


class PublishedProductOut(BaseModel):
    product_id: uuid.UUID | None
    plan_item_id: uuid.UUID
    # None when this is a dry_run preview — nothing has actually been
    # created yet, scheduled_for/will_create_story still reflect what
    # a real call would do.
    publication_plan_id: uuid.UUID | None = None
    scheduled_for: datetime
    story_plan_item_id: uuid.UUID | None = None
    will_create_story: bool = False


class SkippedProductOut(BaseModel):
    product_id: uuid.UUID | None
    plan_item_id: uuid.UUID
    reason: str


class PublishApprovedResponse(BaseModel):
    dry_run: bool
    published: list[PublishedProductOut]
    skipped: list[SkippedProductOut]


class AutoPilotPolicyOut(BaseModel):
    id: uuid.UUID
    allowed_platforms: list[str]
    max_total_spend: Decimal
    blocked_topics: list[str]
    posting_window_start_hour: int
    posting_window_end_hour: int
    kill_switch_active: bool

    model_config = {"from_attributes": True}
