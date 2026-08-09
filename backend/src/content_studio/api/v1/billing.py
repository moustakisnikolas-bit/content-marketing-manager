from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from content_studio.api.deps import WorkspaceContext, get_db_session, get_workspace_context
from content_studio.modules.billing.schemas import SubscriptionBalanceOut
from content_studio.modules.billing.service import LedgerService

router = APIRouter(prefix="/billing", tags=["billing"])


@router.get("/subscription", response_model=SubscriptionBalanceOut)
async def get_subscription_balance(
    context: WorkspaceContext = Depends(get_workspace_context),
    session: AsyncSession = Depends(get_db_session),
) -> SubscriptionBalanceOut:
    ledger = LedgerService(session)
    balance = await ledger.get_balance(context.subscription_id)
    return SubscriptionBalanceOut(subscription_id=context.subscription_id, credit_balance=balance)
