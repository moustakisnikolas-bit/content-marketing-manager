import uuid
from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, Field


class MetricDefinitionOut(BaseModel):
    id: uuid.UUID
    name: str
    unit: str
    scope: str
    description: str

    model_config = {"from_attributes": True}


class MetricSnapshotOut(BaseModel):
    id: uuid.UUID
    metric_definition_id: uuid.UUID
    raw_provider_name: str
    raw_payload: dict
    normalized_value: Decimal
    measurement_time: datetime
    collection_time: datetime
    publication_attempt_id: uuid.UUID | None
    campaign_plan_item_id: uuid.UUID | None

    model_config = {"from_attributes": True}


class IngestMetricsRequest(BaseModel):
    publication_attempt_id: uuid.UUID


class IngestMetricsResponse(BaseModel):
    snapshots: list[MetricSnapshotOut]


class RecordConversionEventRequest(BaseModel):
    event_type: str = Field(min_length=1, max_length=50)
    occurred_at: datetime
    source: str = Field(min_length=1, max_length=100)
    campaign_plan_item_id: uuid.UUID | None = None
    value: Decimal | None = None
    currency: str | None = Field(default=None, min_length=3, max_length=3)
    consent_confirmed: bool = False


class ConversionEventOut(BaseModel):
    id: uuid.UUID
    event_type: str
    occurred_at: datetime
    source: str
    campaign_plan_item_id: uuid.UUID | None
    value: Decimal | None
    currency: str | None
    consent_confirmed: bool

    model_config = {"from_attributes": True}


class GenerateBestPostingTimeRequest(BaseModel):
    metric_name: str = Field(default="engagement_rate", min_length=1, max_length=100)
    data_window_days: int = Field(default=90, ge=1, le=365)


class GenerateCampaignComparisonRequest(BaseModel):
    name: str = Field(min_length=1, max_length=300)
    campaign_a_id: uuid.UUID
    campaign_b_id: uuid.UUID
    metric_name: str = Field(default="engagement_rate", min_length=1, max_length=100)


class RecommendationOut(BaseModel):
    id: uuid.UUID
    recommendation_type: str
    objective: str
    score: Decimal
    confidence: str
    evidence: dict
    sample_size: int
    data_window_days: int
    explanation: str
    expires_at: datetime
    created_at: datetime

    model_config = {"from_attributes": True}


class RecordRecommendationOutcomeRequest(BaseModel):
    outcome: str = Field(pattern="^(acted_on|dismissed|expired)$")
    notes: str | None = Field(default=None, max_length=1000)


class RecommendationOutcomeOut(BaseModel):
    outcome: str
    notes: str | None
    recorded_at: datetime

    model_config = {"from_attributes": True}


class RecommendationDetailOut(BaseModel):
    recommendation: RecommendationOut
    outcomes: list[RecommendationOutcomeOut]


class ExperimentOut(BaseModel):
    id: uuid.UUID
    name: str
    campaign_a_id: uuid.UUID
    campaign_b_id: uuid.UUID
    metric_definition_id: uuid.UUID
    winner: str
    evidence: dict
    result_summary: str
    created_at: datetime

    model_config = {"from_attributes": True}
