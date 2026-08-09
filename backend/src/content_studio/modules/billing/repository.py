import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from content_studio.modules.billing.models import (
    CostReservation,
    CustomerSubscription,
    SubscriptionPlan,
    UsageLedgerEntry,
)


class BillingRepository:
    """Owns all direct ORM access for the billing module."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_plan_by_slug(self, slug: str) -> SubscriptionPlan | None:
        result = await self._session.execute(select(SubscriptionPlan).where(SubscriptionPlan.slug == slug))
        return result.scalar_one_or_none()

    async def create_plan(
        self, *, name: str, slug: str, monthly_price: Decimal, monthly_credit_allowance: Decimal, currency: str = "EUR"
    ) -> SubscriptionPlan:
        plan = SubscriptionPlan(
            name=name,
            slug=slug,
            monthly_price=monthly_price,
            currency=currency,
            monthly_credit_allowance=monthly_credit_allowance,
        )
        self._session.add(plan)
        await self._session.flush()
        return plan

    async def get_subscription_for_organization(
        self, organization_id: uuid.UUID
    ) -> CustomerSubscription | None:
        result = await self._session.execute(
            select(CustomerSubscription).where(CustomerSubscription.organization_id == organization_id)
        )
        return result.scalar_one_or_none()

    async def get_subscription_by_id(self, subscription_id: uuid.UUID) -> CustomerSubscription | None:
        return await self._session.get(CustomerSubscription, subscription_id)

    async def get_subscription_for_update(self, subscription_id: uuid.UUID) -> CustomerSubscription | None:
        """Row-locked read, so concurrent reserve/settle/release calls on
        the same subscription serialize instead of racing on the shared
        credit_balance."""
        result = await self._session.execute(
            select(CustomerSubscription)
            .where(CustomerSubscription.id == subscription_id)
            .with_for_update()
        )
        return result.scalar_one_or_none()

    async def create_subscription(
        self, *, organization_id: uuid.UUID, plan_id: uuid.UUID, initial_balance: Decimal
    ) -> CustomerSubscription:
        now = datetime.now(UTC)
        subscription = CustomerSubscription(
            organization_id=organization_id,
            plan_id=plan_id,
            status="active",
            credit_balance=initial_balance,
            current_period_start=now,
            current_period_end=now + timedelta(days=30),
        )
        self._session.add(subscription)
        await self._session.flush()
        return subscription

    async def get_reservation_by_idempotency_key(self, idempotency_key: str) -> CostReservation | None:
        result = await self._session.execute(
            select(CostReservation).where(CostReservation.idempotency_key == idempotency_key)
        )
        return result.scalar_one_or_none()

    async def get_reservation_by_id(self, reservation_id: uuid.UUID) -> CostReservation | None:
        return await self._session.get(CostReservation, reservation_id)

    async def create_reservation(
        self,
        *,
        organization_id: uuid.UUID,
        subscription_id: uuid.UUID,
        idempotency_key: str,
        reference: str,
        reserved_amount: Decimal,
    ) -> CostReservation:
        reservation = CostReservation(
            organization_id=organization_id,
            subscription_id=subscription_id,
            idempotency_key=idempotency_key,
            reference=reference,
            reserved_amount=reserved_amount,
        )
        self._session.add(reservation)
        await self._session.flush()
        return reservation

    async def add_ledger_entry(
        self,
        *,
        organization_id: uuid.UUID,
        subscription_id: uuid.UUID,
        reservation_id: uuid.UUID | None,
        entry_type: str,
        amount: Decimal,
        balance_after: Decimal,
        description: str,
    ) -> UsageLedgerEntry:
        entry = UsageLedgerEntry(
            organization_id=organization_id,
            subscription_id=subscription_id,
            reservation_id=reservation_id,
            entry_type=entry_type,
            amount=amount,
            balance_after=balance_after,
            description=description,
        )
        self._session.add(entry)
        await self._session.flush()
        return entry

    async def list_ledger_entries(self, subscription_id: uuid.UUID) -> list[UsageLedgerEntry]:
        result = await self._session.execute(
            select(UsageLedgerEntry)
            .where(UsageLedgerEntry.subscription_id == subscription_id)
            .order_by(UsageLedgerEntry.created_at)
        )
        return list(result.scalars().all())
