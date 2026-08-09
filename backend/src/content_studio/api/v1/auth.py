from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from content_studio.api.deps import get_current_user, get_db_session, rate_limit_by_client_ip
from content_studio.db.seed import DEFAULT_PLAN_SLUG
from content_studio.modules.billing.service import LedgerService
from content_studio.modules.governance.service import AuditService
from content_studio.modules.identity.exceptions import (
    EmailAlreadyRegistered,
    InvalidCredentials,
    InvalidRefreshToken,
)
from content_studio.modules.identity.models import User
from content_studio.modules.identity.schemas import (
    LoginRequest,
    OrganizationOut,
    RefreshRequest,
    SignupRequest,
    SignupResponse,
    TokenResponse,
    UserOut,
    WorkspaceOut,
)
from content_studio.modules.identity.service import IdentityService

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/signup", response_model=SignupResponse, status_code=status.HTTP_201_CREATED)
async def signup(
    body: SignupRequest,
    session: AsyncSession = Depends(get_db_session),
    _rate_limit: None = Depends(rate_limit_by_client_ip(action="signup", limit=5)),
) -> SignupResponse:
    service = IdentityService(session)
    try:
        result = await service.signup(
            email=body.email,
            password=body.password,
            display_name=body.display_name,
            organization_name=body.organization_name,
        )
    except EmailAlreadyRegistered as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, "Email already registered") from exc

    # Every new organization starts on the default plan with its monthly
    # credit allowance pre-allocated — see db/seed.py for the plan catalog.
    ledger = LedgerService(session)
    await ledger.open_subscription(organization_id=result.organization.id, plan_slug=DEFAULT_PLAN_SLUG)

    audit = AuditService(session)
    await audit.record(
        event_type="identity.signup",
        actor_type="user",
        actor_id=str(result.user.id),
        organization_id=result.organization.id,
        summary=f"{result.user.display_name} created organization '{result.organization.name}'",
        payload={"email": result.user.email, "workspace_id": str(result.workspace.id)},
    )
    await session.commit()

    return SignupResponse(
        user=UserOut.model_validate(result.user),
        organization=OrganizationOut.model_validate(result.organization),
        workspace=WorkspaceOut.model_validate(result.workspace),
        tokens=TokenResponse(
            access_token=result.tokens.access_token, refresh_token=result.tokens.refresh_token
        ),
    )


@router.post("/login", response_model=TokenResponse)
async def login(
    body: LoginRequest,
    session: AsyncSession = Depends(get_db_session),
    _rate_limit: None = Depends(rate_limit_by_client_ip(action="login", limit=10)),
) -> TokenResponse:
    service = IdentityService(session)
    try:
        tokens = await service.login(email=body.email, password=body.password)
    except InvalidCredentials as exc:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid email or password") from exc

    return TokenResponse(access_token=tokens.access_token, refresh_token=tokens.refresh_token)


@router.post("/refresh", response_model=TokenResponse)
async def refresh(body: RefreshRequest, session: AsyncSession = Depends(get_db_session)) -> TokenResponse:
    service = IdentityService(session)
    try:
        tokens = await service.refresh(raw_refresh_token=body.refresh_token)
    except InvalidRefreshToken as exc:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid or expired refresh token") from exc

    return TokenResponse(access_token=tokens.access_token, refresh_token=tokens.refresh_token)


@router.get("/me", response_model=UserOut)
async def me(current_user: User = Depends(get_current_user)) -> UserOut:
    return UserOut.model_validate(current_user)
