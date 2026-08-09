import uuid
from datetime import datetime

from pydantic import BaseModel, Field

from content_studio.modules.creation.models import CONTENT_TYPES

# Derived from the single source of truth (models.py's CHECK constraint
# tuple) instead of a second hardcoded regex — the two drifting apart is
# exactly how content_type="audio" silently 422'd after Audio Studio was
# wired everywhere else. See windows_dev_gotchas.md.
_CONTENT_TYPE_PATTERN = f"^({'|'.join(CONTENT_TYPES)})$"


class AssetOut(BaseModel):
    id: uuid.UUID
    workspace_id: uuid.UUID
    original_filename: str
    content_type: str
    byte_size: int
    created_at: datetime

    model_config = {"from_attributes": True}


class AssetDownloadUrlOut(BaseModel):
    url: str


class CreateBriefRequest(BaseModel):
    content_type: str = Field(pattern=_CONTENT_TYPE_PATTERN)
    title: str = Field(min_length=1, max_length=300)
    brief_text: str = Field(min_length=1, max_length=4000)
    brand_profile_id: uuid.UUID | None = None


class CreateBriefResponse(BaseModel):
    content_item_id: uuid.UUID
    job_id: uuid.UUID


class ContentItemOut(BaseModel):
    id: uuid.UUID
    content_type: str
    title: str
    status: str
    created_at: datetime

    model_config = {"from_attributes": True}


class ContentRevisionOut(BaseModel):
    id: uuid.UUID
    revision_number: int
    kind: str
    text_body: str | None
    asset_id: uuid.UUID | None
    created_at: datetime

    model_config = {"from_attributes": True}


class ContentPackageOut(BaseModel):
    id: uuid.UUID
    selected_revision_id: uuid.UUID
    packaged_at: datetime

    model_config = {"from_attributes": True}


class ContentItemDetailOut(BaseModel):
    item: ContentItemOut
    revisions: list[ContentRevisionOut]
    package: ContentPackageOut | None


class GenerationJobOut(BaseModel):
    id: uuid.UUID
    content_item_id: uuid.UUID
    status: str
    failure_reason: str | None
    created_at: datetime

    model_config = {"from_attributes": True}


class ReviewRequest(BaseModel):
    decision: str = Field(pattern="^(approved|rejected)$")
    revision_id: uuid.UUID
    comment: str | None = Field(default=None, max_length=1000)
