import uuid
from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, Field


class AgentOut(BaseModel):
    id: uuid.UUID
    name: str
    display_name: str
    mcp_domain: str
    description: str
    status: str

    model_config = {"from_attributes": True}


class ToolOut(BaseModel):
    id: uuid.UUID
    agent_id: uuid.UUID
    name: str
    version: str
    risk_level: str
    description: str
    requires_approval: bool
    status: str

    model_config = {"from_attributes": True}


class RequestToolApprovalRequest(BaseModel):
    tool_id: uuid.UUID
    payload: dict
    destination: str | None = None
    cost: Decimal | None = None


class ToolApprovalOut(BaseModel):
    id: uuid.UUID
    tool_registration_id: uuid.UUID
    status: str
    destination: str | None
    cost: Decimal | None
    expires_at: datetime
    approved_at: datetime | None
    used_at: datetime | None
    created_at: datetime

    model_config = {"from_attributes": True}


class CallGenerateProductCampaignRequest(BaseModel):
    product_id: uuid.UUID
    goal_slug: str
    mode: str = Field(pattern="^(manual|guided|autopilot)$")
    target_platforms: list[str] = Field(default_factory=list)


class CallGenerateBestPostingTimeRequest(BaseModel):
    metric_name: str = Field(default="engagement_rate", min_length=1, max_length=100)
    data_window_days: int = Field(default=90, ge=1, le=365)


class ToolCallResultOut(BaseModel):
    authorized: bool
    result: dict


class AuditEventOut(BaseModel):
    id: uuid.UUID
    event_type: str
    actor_type: str
    actor_id: str | None
    summary: str
    payload: dict
    request_id: str | None
    correlation_id: str | None
    trace_id: str | None
    tool_call_id: str | None
    workflow_id: str | None
    business_operation_id: str | None
    created_at: datetime

    model_config = {"from_attributes": True}
