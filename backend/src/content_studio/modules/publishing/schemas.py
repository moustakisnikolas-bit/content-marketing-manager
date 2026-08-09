import uuid
from datetime import datetime

from pydantic import BaseModel, Field


class AuthorizationUrlOut(BaseModel):
    authorization_url: str


class CapabilityOut(BaseModel):
    capability: str
    is_available: bool
    reason: str | None

    model_config = {"from_attributes": True}


class PlatformConnectionOut(BaseModel):
    id: uuid.UUID
    platform: str
    external_account_name: str
    status: str
    created_at: datetime

    model_config = {"from_attributes": True}


class ConnectionDetailOut(BaseModel):
    connection: PlatformConnectionOut
    capabilities: list[CapabilityOut]


class ConnectableAccountOut(BaseModel):
    external_account_id: str
    external_account_name: str


class PendingPageSelectionOut(BaseModel):
    """Returned instead of ConnectionDetailOut when the OAuth exchange
    could publish as more than one account (Meta: multiple Facebook
    Pages) — the caller must show a picker and POST the choice to
    /publishing/oauth/select-page."""

    pending_token: str
    accounts: list[ConnectableAccountOut]


class SelectPageRequest(BaseModel):
    pending_token: str
    external_account_id: str


class CreatePublicationPlanRequest(BaseModel):
    content_item_id: uuid.UUID
    platform_connection_id: uuid.UUID
    scheduled_for: datetime | None = None
    target_format: str = Field(default="post", pattern="^(post|story)$")


class CreatePublicationPlanResponse(BaseModel):
    plan_id: uuid.UUID


class PublicationPlanOut(BaseModel):
    id: uuid.UUID
    content_item_id: uuid.UUID
    platform_connection_id: uuid.UUID
    status: str
    scheduled_for: datetime | None
    target_format: str
    failure_reason: str | None
    created_at: datetime

    model_config = {"from_attributes": True}


class PublicationReviewRequest(BaseModel):
    decision: str = Field(pattern="^(approved|rejected)$")
    comment: str | None = Field(default=None, max_length=1000)


class PublicationAttemptOut(BaseModel):
    id: uuid.UUID
    attempt_number: int
    status: str
    external_post_id: str | None
    error_message: str | None

    model_config = {"from_attributes": True}


class ReconciliationOut(BaseModel):
    matches_expected: bool
    external_status: str
    checked_at: datetime

    model_config = {"from_attributes": True}


class PublicationAttemptDetailOut(BaseModel):
    attempt: PublicationAttemptOut
    reconciliations: list[ReconciliationOut]
