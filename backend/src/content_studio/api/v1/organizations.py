import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from content_studio.api.deps import (
    WorkspaceContext,
    get_current_user,
    get_db_session,
    get_workspace_context,
    require_permission,
)
from content_studio.modules.identity.exceptions import (
    InvitationNotFound,
    InvitationNotPending,
    RoleNotFound,
    WorkspaceNotFound,
)
from content_studio.modules.identity.models import User
from content_studio.modules.identity.repository import IdentityRepository
from content_studio.modules.identity.schemas import (
    AcceptInvitationRequest,
    CreateInvitationRequest,
    CreateInvitationResponse,
    CreateWorkspaceRequest,
    InvitationOut,
    MyWorkspaceOut,
    OrganizationBrandingOut,
    RoleOut,
    UpdateOrganizationBrandingRequest,
    WorkspaceOut,
)
from content_studio.modules.identity.service import IdentityService

router = APIRouter(prefix="/organizations", tags=["organizations"])


@router.get("/workspaces", response_model=list[MyWorkspaceOut])
async def list_my_workspaces(
    current_user: User = Depends(get_current_user), session: AsyncSession = Depends(get_db_session)
) -> list[MyWorkspaceOut]:
    """Powers the workspace switcher — every workspace the caller has a
    Membership in, across every organization, with their role in each.
    Pass the chosen workspace's id as X-Workspace-Id on subsequent calls."""
    service = IdentityService(session)
    pairs = await service.list_workspaces_for_user(current_user.id)
    return [
        MyWorkspaceOut(workspace=WorkspaceOut.model_validate(w), role=RoleOut.model_validate(r)) for w, r in pairs
    ]


@router.post("/workspaces", response_model=WorkspaceOut, status_code=status.HTTP_201_CREATED)
async def create_workspace(
    body: CreateWorkspaceRequest,
    current_user: User = Depends(get_current_user),
    context: WorkspaceContext = Depends(require_permission("workspace:manage")),
    session: AsyncSession = Depends(get_db_session),
) -> WorkspaceOut:
    """The agency primitive: create another client/brand workspace within
    the caller's own organization. Requires workspace:manage (Owner or
    Admin) in whichever workspace X-Workspace-Id currently resolves to —
    the new workspace is created under that same organization."""
    service = IdentityService(session)
    workspace = await service.create_workspace(
        organization_id=context.organization_id, name=body.name, owner_user_id=current_user.id,
    )
    return WorkspaceOut.model_validate(workspace)


@router.post("/workspaces/{workspace_id}/invitations", response_model=CreateInvitationResponse, status_code=status.HTTP_201_CREATED)
async def create_invitation(
    workspace_id: uuid.UUID,
    body: CreateInvitationRequest,
    current_user: User = Depends(get_current_user),
    context: WorkspaceContext = Depends(require_permission("membership:manage")),
    session: AsyncSession = Depends(get_db_session),
) -> CreateInvitationResponse:
    if workspace_id != context.workspace_id:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Switch to this workspace (X-Workspace-Id) to invite to it")

    service = IdentityService(session)
    try:
        invitation, raw_token = await service.invite_to_workspace(
            workspace_id=workspace_id, email=body.email, role_name=body.role_name,
            invited_by_user_id=current_user.id,
        )
    except WorkspaceNotFound as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Workspace not found") from exc
    except RoleNotFound as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, f"Unknown role {exc}") from exc

    return CreateInvitationResponse(invitation=InvitationOut.model_validate(invitation), invite_token=raw_token)


@router.get("/workspaces/{workspace_id}/invitations", response_model=list[InvitationOut])
async def list_pending_invitations(
    workspace_id: uuid.UUID,
    context: WorkspaceContext = Depends(require_permission("membership:manage")),
    session: AsyncSession = Depends(get_db_session),
) -> list[InvitationOut]:
    if workspace_id != context.workspace_id:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Switch to this workspace (X-Workspace-Id) to view its invitations")
    repo = IdentityRepository(session)
    invitations = await repo.list_pending_invitations_for_workspace(workspace_id)
    return [InvitationOut.model_validate(i) for i in invitations]


@router.post("/invitations/accept", response_model=dict)
async def accept_invitation(
    body: AcceptInvitationRequest,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_session),
) -> dict:
    service = IdentityService(session)
    try:
        membership = await service.accept_invitation(raw_token=body.token, accepting_user=current_user)
    except (InvitationNotFound, InvitationNotPending) as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "This invitation is invalid, expired, or already used") from exc
    return {"workspace_id": str(membership.workspace_id), "status": "accepted"}


@router.get("/branding", response_model=OrganizationBrandingOut)
async def get_organization_branding(
    context: WorkspaceContext = Depends(get_workspace_context), session: AsyncSession = Depends(get_db_session)
) -> OrganizationBrandingOut:
    repo = IdentityRepository(session)
    organization = await repo.get_organization_by_id(context.organization_id)
    assert organization is not None
    return OrganizationBrandingOut(
        product_name=organization.branding_product_name, logo_url=organization.branding_logo_url,
        primary_color=organization.branding_primary_color,
    )


@router.put("/branding", response_model=OrganizationBrandingOut)
async def update_organization_branding(
    body: UpdateOrganizationBrandingRequest,
    context: WorkspaceContext = Depends(require_permission("workspace:manage")),
    session: AsyncSession = Depends(get_db_session),
) -> OrganizationBrandingOut:
    """White-label scaffold: a handful of fields the frontend applies as
    CSS custom-property overrides. Not a full theming system — that stays
    a documented follow-up, per the Phase 8 plan's own 'scaffolded, not
    fully built' scope for this piece."""
    service = IdentityService(session)
    organization = await service.update_organization_branding(
        organization_id=context.organization_id, product_name=body.product_name, logo_url=body.logo_url,
        primary_color=body.primary_color,
    )
    return OrganizationBrandingOut(
        product_name=organization.branding_product_name, logo_url=organization.branding_logo_url,
        primary_color=organization.branding_primary_color,
    )
