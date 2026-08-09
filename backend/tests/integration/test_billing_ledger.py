import uuid
from decimal import Decimal

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from content_studio.modules.billing.exceptions import InsufficientCredits
from content_studio.modules.billing.service import LedgerService
from content_studio.modules.identity.service import IdentityService

pytestmark = pytest.mark.asyncio


async def _seed_organization(session: AsyncSession) -> uuid.UUID:
    identity = IdentityService(session)
    email = f"billing-{uuid.uuid4().hex[:12]}@example.com"
    result = await identity.signup(
        email=email, password="correct-horse-battery", display_name="Billing Test", organization_name="Billing Org"
    )
    return result.organization.id


async def _seed_subscription(session: AsyncSession, *, allowance: Decimal = Decimal(100)) -> tuple[uuid.UUID, uuid.UUID]:
    from content_studio.modules.billing.repository import BillingRepository

    organization_id = await _seed_organization(session)
    repo = BillingRepository(session)
    plan_slug = f"plan-{uuid.uuid4().hex[:8]}"
    plan = await repo.create_plan(
        name=plan_slug, slug=plan_slug, monthly_price=Decimal("39.00"), monthly_credit_allowance=allowance
    )
    await session.commit()

    ledger = LedgerService(session)
    subscription_id = await ledger.open_subscription(organization_id=organization_id, plan_slug=plan.slug)
    return organization_id, subscription_id


async def test_open_subscription_allocates_plan_credit_balance(db_session: AsyncSession) -> None:
    ledger = LedgerService(db_session)
    _, subscription_id = await _seed_subscription(db_session, allowance=Decimal(250))

    balance = await ledger.get_balance(subscription_id)
    assert balance == Decimal("250.0000")


async def test_reserve_deducts_balance_immediately(db_session: AsyncSession) -> None:
    ledger = LedgerService(db_session)
    organization_id, subscription_id = await _seed_subscription(db_session)

    await ledger.reserve(
        organization_id=organization_id,
        subscription_id=subscription_id,
        amount=Decimal(10),
        reference="asset_upload:test",
        idempotency_key=f"key-{uuid.uuid4()}",
    )

    balance = await ledger.get_balance(subscription_id)
    assert balance == Decimal("90.0000")


async def test_settle_under_reserved_amount_refunds_the_difference(db_session: AsyncSession) -> None:
    ledger = LedgerService(db_session)
    organization_id, subscription_id = await _seed_subscription(db_session)

    reservation = await ledger.reserve(
        organization_id=organization_id,
        subscription_id=subscription_id,
        amount=Decimal(20),
        reference="generation_job:test",
        idempotency_key=f"key-{uuid.uuid4()}",
    )
    await ledger.settle(reservation_id=reservation.id, actual_amount=Decimal(12))

    balance = await ledger.get_balance(subscription_id)
    # 100 - 20 (reserved) + 8 (released difference) = 88
    assert balance == Decimal("88.0000")


async def test_settle_over_reserved_amount_deducts_overage(db_session: AsyncSession) -> None:
    ledger = LedgerService(db_session)
    organization_id, subscription_id = await _seed_subscription(db_session)

    reservation = await ledger.reserve(
        organization_id=organization_id,
        subscription_id=subscription_id,
        amount=Decimal(10),
        reference="generation_job:overage",
        idempotency_key=f"key-{uuid.uuid4()}",
    )
    await ledger.settle(reservation_id=reservation.id, actual_amount=Decimal(14))

    balance = await ledger.get_balance(subscription_id)
    # 100 - 10 (reserved) - 4 (overage beyond reservation) = 86
    assert balance == Decimal("86.0000")


async def test_release_refunds_full_reservation(db_session: AsyncSession) -> None:
    ledger = LedgerService(db_session)
    organization_id, subscription_id = await _seed_subscription(db_session)

    reservation = await ledger.reserve(
        organization_id=organization_id,
        subscription_id=subscription_id,
        amount=Decimal(30),
        reference="generation_job:failed_before_dispatch",
        idempotency_key=f"key-{uuid.uuid4()}",
    )
    await ledger.release(reservation_id=reservation.id)

    balance = await ledger.get_balance(subscription_id)
    assert balance == Decimal("100.0000")


async def test_reserve_raises_when_balance_insufficient(db_session: AsyncSession) -> None:
    ledger = LedgerService(db_session)
    organization_id, subscription_id = await _seed_subscription(db_session, allowance=Decimal(5))

    with pytest.raises(InsufficientCredits):
        await ledger.reserve(
            organization_id=organization_id,
            subscription_id=subscription_id,
            amount=Decimal(10),
            reference="asset_upload:too_expensive",
            idempotency_key=f"key-{uuid.uuid4()}",
        )


async def test_reserve_is_idempotent_for_same_key(db_session: AsyncSession) -> None:
    ledger = LedgerService(db_session)
    organization_id, subscription_id = await _seed_subscription(db_session)
    key = f"key-{uuid.uuid4()}"

    first = await ledger.reserve(
        organization_id=organization_id,
        subscription_id=subscription_id,
        amount=Decimal(10),
        reference="asset_upload:retry",
        idempotency_key=key,
    )
    second = await ledger.reserve(
        organization_id=organization_id,
        subscription_id=subscription_id,
        amount=Decimal(10),
        reference="asset_upload:retry",
        idempotency_key=key,
    )

    assert first.id == second.id
    balance = await ledger.get_balance(subscription_id)
    # Only deducted once, despite two reserve() calls with the same key.
    assert balance == Decimal("90.0000")


async def test_ledger_entries_are_append_only_audit_trail(db_session: AsyncSession) -> None:
    from content_studio.modules.billing.repository import BillingRepository

    organization_id, subscription_id = await _seed_subscription(db_session)
    ledger = LedgerService(db_session)

    reservation = await ledger.reserve(
        organization_id=organization_id,
        subscription_id=subscription_id,
        amount=Decimal(15),
        reference="generation_job:audit_trail",
        idempotency_key=f"key-{uuid.uuid4()}",
    )
    await ledger.settle(reservation_id=reservation.id, actual_amount=Decimal(9))

    repo = BillingRepository(db_session)
    entries = await repo.list_ledger_entries(subscription_id)
    entry_types = [e.entry_type for e in entries]

    assert "allocation" in entry_types
    assert "reservation" in entry_types
    assert "release" in entry_types
