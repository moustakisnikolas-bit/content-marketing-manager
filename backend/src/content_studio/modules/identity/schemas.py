import uuid
from datetime import datetime

from pydantic import BaseModel, EmailStr, Field


class SignupRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8, max_length=200)
    display_name: str = Field(min_length=1, max_length=200)
    organization_name: str = Field(min_length=1, max_length=200)


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class RefreshRequest(BaseModel):
    refresh_token: str


class AddMemberRequest(BaseModel):
    invitee_email: EmailStr
    role_name: str = Field(default="Owner", max_length=100)


class TokenResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"


class OrganizationOut(BaseModel):
    id: uuid.UUID
    name: str
    slug: str

    model_config = {"from_attributes": True}


class WorkspaceOut(BaseModel):
    id: uuid.UUID
    organization_id: uuid.UUID
    name: str
    slug: str

    model_config = {"from_attributes": True}


class UserOut(BaseModel):
    id: uuid.UUID
    email: str
    display_name: str
    is_active: bool

    model_config = {"from_attributes": True}


class SignupResponse(BaseModel):
    user: UserOut
    organization: OrganizationOut
    workspace: WorkspaceOut
    tokens: TokenResponse


class RoleOut(BaseModel):
    id: uuid.UUID
    name: str
    permissions: list[str]

    model_config = {"from_attributes": True}


class MyWorkspaceOut(BaseModel):
    workspace: WorkspaceOut
    role: RoleOut


class CreateWorkspaceRequest(BaseModel):
    name: str = Field(min_length=1, max_length=200)


class CreateInvitationRequest(BaseModel):
    email: EmailStr
    role_name: str = Field(default="Editor", max_length=100)


class InvitationOut(BaseModel):
    id: uuid.UUID
    workspace_id: uuid.UUID
    email: str
    status: str
    expires_at: datetime
    created_at: datetime

    model_config = {"from_attributes": True}


class CreateInvitationResponse(BaseModel):
    invitation: InvitationOut
    invite_token: str


class AcceptInvitationRequest(BaseModel):
    token: str


class OrganizationBrandingOut(BaseModel):
    product_name: str | None
    logo_url: str | None
    primary_color: str | None


class UpdateOrganizationBrandingRequest(BaseModel):
    product_name: str | None = Field(default=None, max_length=200)
    logo_url: str | None = Field(default=None, max_length=2000)
    primary_color: str | None = Field(default=None, min_length=4, max_length=7, pattern="^#[0-9a-fA-F]{3,6}$")


class CreateApiKeyRequest(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    scopes: list[str] = Field(default_factory=lambda: ["analytics:read"])


class ApiKeyOut(BaseModel):
    id: uuid.UUID
    name: str
    key_prefix: str
    scopes: list[str]
    status: str
    last_used_at: datetime | None
    created_at: datetime

    model_config = {"from_attributes": True}


class CreateApiKeyResponse(BaseModel):
    api_key: ApiKeyOut
    raw_key: str


class BrandRuleOut(BaseModel):
    id: uuid.UUID
    rule_type: str
    description: str
    is_blocking: bool

    model_config = {"from_attributes": True}


class CreateBrandRuleRequest(BaseModel):
    rule_type: str = Field(min_length=1, max_length=50)
    description: str = Field(min_length=1, max_length=2000)
    is_blocking: bool = True


class BrandProfileOut(BaseModel):
    id: uuid.UUID
    name: str
    tone_description: str | None
    vocabulary: list[str]
    colors: list[str]
    target_audiences: list[str]
    default_ctas: list[str]
    is_active: bool

    model_config = {"from_attributes": True}


class BrandProfileDetailOut(BaseModel):
    profile: BrandProfileOut
    rules: list[BrandRuleOut]


class CreateBrandProfileRequest(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    tone_description: str | None = Field(default=None, max_length=2000)
    vocabulary: list[str] = Field(default_factory=list)
    colors: list[str] = Field(default_factory=list)
    target_audiences: list[str] = Field(default_factory=list)
    default_ctas: list[str] = Field(default_factory=list)


class UpdateBrandProfileRequest(CreateBrandProfileRequest):
    is_active: bool = True
