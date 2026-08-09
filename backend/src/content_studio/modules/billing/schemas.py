import uuid
from decimal import Decimal

from pydantic import BaseModel


class SubscriptionBalanceOut(BaseModel):
    subscription_id: uuid.UUID
    credit_balance: Decimal
