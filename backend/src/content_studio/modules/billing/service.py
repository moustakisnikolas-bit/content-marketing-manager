import uuid
from datetime import UTC, datetime
from decimal import Decimal

from sqlalchemy.ext.asyncio import AsyncSession

from content_studio.modules.billing.exceptions import (
    InsufficientCredits,
    ReservationNotFound,
    ReservationNotReserved,
    SubscriptionNotFound,
)
from content_studio.modules.billing.models import (
    CostReservation,
    LedgerEntryType,
    ReservationStatus,
)
from content_studio.modules.billing.repository import BillingRepository


class LedgerService:
    """Native credit ledger: reserve -> settle -> release. Every job
    reserves cost/entitlement before dispatch and settles actual use
    afterward, per 22_BILLING_AND_PRICING_MODEL.md. Deliberately not backed
    by a third-party billing engine — see docs/adr/0002 and the billing row
    in 28_OSS_TECHNOLOGY_STACK.md for why."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self._repo = BillingRepository(session)

    async def open_subscription(
        self, *, organization_id: uuid.UUID, plan_slug: str
    ) -> uuid.UUID:
        plan = await self._repo.get_plan_by_slug(plan_slug)
        if plan is None:
            raise SubscriptionNotFound(f"plan {plan_slug} not found")

        subscription = await self._repo.create_subscription(
            organization_id=organization_id,
            plan_id=plan.id,
            initial_balance=Decimal(0),
        )
        await self._allocate(
            subscription_id=subscription.id,
            organization_id=organization_id,
            amount=plan.monthly_credit_allowance,
            description=f"Initial allocation for plan {plan.name}",
        )
        await self._session.commit()
        return subscription.id

    async def reserve(
        self,
        *,
        organization_id: uuid.UUID,
        subscription_id: uuid.UUID,
        amount: Decimal,
        reference: str,
        idempotency_key: str,
    ) -> CostReservation:
        existing = await self._repo.get_reservation_by_idempotency_key(idempotency_key)
        if existing is not None:
            return existing

        subscription = await self._repo.get_subscription_for_update(subscription_id)
        if subscription is None:
            raise SubscriptionNotFound(str(subscription_id))
        if subscription.credit_balance < amount:
            raise InsufficientCredits(
                f"balance {subscription.credit_balance} < requested {amount}"
            )

        reservation = await self._repo.create_reservation(
            organization_id=organization_id,
            subscription_id=subscription_id,
            idempotency_key=idempotency_key,
            reference=reference,
            reserved_amount=amount,
        )
        subscription.credit_balance -= amount
        await self._repo.add_ledger_entry(
            organization_id=organization_id,
            subscription_id=subscription_id,
            reservation_id=reservation.id,
            entry_type=LedgerEntryType.RESERVATION.value,
            amount=-amount,
            balance_after=subscription.credit_balance,
            description=f"Reserved for {reference}",
        )
        await self._session.commit()
        return reservation

    async def settle(
        self, *, reservation_id: uuid.UUID, actual_amount: Decimal
    ) -> CostReservation:
        reservation = await self._repo.get_reservation_by_id(reservation_id)
        if reservation is None:
            raise ReservationNotFound(str(reservation_id))
        if reservation.status != ReservationStatus.RESERVED.value:
            raise ReservationNotReserved(reservation.status)

        subscription = await self._repo.get_subscription_for_update(reservation.subscription_id)
        assert subscription is not None

        difference = reservation.reserved_amount - actual_amount
        if difference > 0:
            subscription.credit_balance += difference
            await self._repo.add_ledger_entry(
                organization_id=reservation.organization_id,
                subscription_id=reservation.subscription_id,
                reservation_id=reservation.id,
                entry_type=LedgerEntryType.RELEASE.value,
                amount=difference,
                balance_after=subscription.credit_balance,
                description=f"Released unused reservation for {reservation.reference}",
            )
        elif difference < 0:
            overage = -difference
            subscription.credit_balance -= overage
            await self._repo.add_ledger_entry(
                organization_id=reservation.organization_id,
                subscription_id=reservation.subscription_id,
                reservation_id=reservation.id,
                entry_type=LedgerEntryType.OVERAGE.value,
                amount=-overage,
                balance_after=subscription.credit_balance,
                description=f"Overage beyond reservation for {reservation.reference}",
            )

        reservation.status = ReservationStatus.SETTLED.value
        reservation.settled_amount = actual_amount
        reservation.settled_at = datetime.now(UTC)
        await self._session.commit()
        return reservation

    async def release(self, *, reservation_id: uuid.UUID) -> CostReservation:
        """Full refund of an unsettled reservation — e.g. a generation
        attempt failed before any provider cost was actually incurred."""
        reservation = await self._repo.get_reservation_by_id(reservation_id)
        if reservation is None:
            raise ReservationNotFound(str(reservation_id))
        if reservation.status != ReservationStatus.RESERVED.value:
            raise ReservationNotReserved(reservation.status)

        subscription = await self._repo.get_subscription_for_update(reservation.subscription_id)
        assert subscription is not None

        subscription.credit_balance += reservation.reserved_amount
        await self._repo.add_ledger_entry(
            organization_id=reservation.organization_id,
            subscription_id=reservation.subscription_id,
            reservation_id=reservation.id,
            entry_type=LedgerEntryType.RELEASE.value,
            amount=reservation.reserved_amount,
            balance_after=subscription.credit_balance,
            description=f"Released reservation for {reservation.reference}",
        )
        reservation.status = ReservationStatus.RELEASED.value
        reservation.released_at = datetime.now(UTC)
        await self._session.commit()
        return reservation

    async def get_balance(self, subscription_id: uuid.UUID) -> Decimal:
        subscription = await self._repo.get_subscription_by_id(subscription_id)
        if subscription is None:
            raise SubscriptionNotFound(str(subscription_id))
        return subscription.credit_balance

    async def _allocate(
        self, *, subscription_id: uuid.UUID, organization_id: uuid.UUID, amount: Decimal, description: str
    ) -> None:
        subscription = await self._repo.get_subscription_for_update(subscription_id)
        assert subscription is not None
        subscription.credit_balance += amount
        await self._repo.add_ledger_entry(
            organization_id=organization_id,
            subscription_id=subscription_id,
            reservation_id=None,
            entry_type=LedgerEntryType.ALLOCATION.value,
            amount=amount,
            balance_after=subscription.credit_balance,
            description=description,
        )
