import enum
import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Numeric,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from content_studio.db.base import Base, TenantScopedMixin, TimestampMixin, UUIDPrimaryKeyMixin


class ReservationStatus(str, enum.Enum):
    RESERVED = "reserved"
    SETTLED = "settled"
    RELEASED = "released"


class LedgerEntryType(str, enum.Enum):
    """Matches 22_BILLING_AND_PRICING_MODEL.md's ledger operation list."""

    ALLOCATION = "allocation"
    RESERVATION = "reservation"
    CONSUMPTION = "consumption"
    RELEASE = "release"
    ADJUSTMENT = "adjustment"
    REFUND = "refund"
    OVERAGE = "overage"


class SubscriptionPlan(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Catalog entity — not tenant-scoped, since a plan is offered to every
    organization, not owned by one."""

    __tablename__ = "subscription_plans"

    name: Mapped[str] = mapped_column(String(100), nullable=False, unique=True)
    slug: Mapped[str] = mapped_column(String(100), nullable=False, unique=True)
    monthly_price: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False, default="EUR")
    monthly_credit_allowance: Mapped[Decimal] = mapped_column(Numeric(14, 4), nullable=False)
    is_active: Mapped[bool] = mapped_column(default=True, nullable=False)


class CustomerSubscription(UUIDPrimaryKeyMixin, TimestampMixin, TenantScopedMixin, Base):
    __tablename__ = "customer_subscriptions"
    __table_args__ = (
        ForeignKeyConstraint(
            ["organization_id"], ["organizations.id"], ondelete="CASCADE",
            name="fk_customer_subscriptions_organization_id_organizations",
        ),
        UniqueConstraint("organization_id", name="uq_customer_subscription_organization"),
    )

    plan_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("subscription_plans.id", ondelete="RESTRICT"), nullable=False
    )
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="active")
    credit_balance: Mapped[Decimal] = mapped_column(Numeric(14, 4), nullable=False, default=Decimal(0))
    current_period_start: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    current_period_end: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    plan: Mapped["SubscriptionPlan"] = relationship()
    reservations: Mapped[list["CostReservation"]] = relationship(back_populates="subscription")
    ledger_entries: Mapped[list["UsageLedgerEntry"]] = relationship(back_populates="subscription")


class CostReservation(UUIDPrimaryKeyMixin, TimestampMixin, TenantScopedMixin, Base):
    """Reserve -> settle -> release. Reservations are never updated in
    place beyond their status/settlement fields — the UsageLedgerEntry rows
    are the immutable append-only record of what actually happened to the
    balance."""

    __tablename__ = "cost_reservations"
    __table_args__ = (
        ForeignKeyConstraint(
            ["organization_id"], ["organizations.id"], ondelete="CASCADE",
            name="fk_cost_reservations_organization_id_organizations",
        ),
        CheckConstraint(
            "status in ('reserved', 'settled', 'released')", name="ck_cost_reservation_status"
        ),
        UniqueConstraint("idempotency_key", name="uq_cost_reservation_idempotency_key"),
    )

    subscription_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("customer_subscriptions.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    idempotency_key: Mapped[str] = mapped_column(String(200), nullable=False)
    reference: Mapped[str] = mapped_column(String(300), nullable=False)
    reserved_amount: Mapped[Decimal] = mapped_column(Numeric(14, 4), nullable=False)
    settled_amount: Mapped[Decimal | None] = mapped_column(Numeric(14, 4), nullable=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default=ReservationStatus.RESERVED.value)
    settled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    released_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    subscription: Mapped["CustomerSubscription"] = relationship(back_populates="reservations")


class UsageLedgerEntry(UUIDPrimaryKeyMixin, TenantScopedMixin, Base):
    """Append-only. No TimestampMixin's updated_at — a ledger entry, once
    written, is never modified, only ever superseded by a new entry."""

    __tablename__ = "usage_ledger_entries"
    __table_args__ = (
        ForeignKeyConstraint(
            ["organization_id"], ["organizations.id"], ondelete="CASCADE",
            name="fk_usage_ledger_entries_organization_id_organizations",
        ),
        CheckConstraint(
            "entry_type in ('allocation','reservation','consumption','release','adjustment','refund','overage')",
            name="ck_usage_ledger_entry_type",
        ),
    )

    subscription_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("customer_subscriptions.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    reservation_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("cost_reservations.id", ondelete="SET NULL"), nullable=True, index=True
    )
    entry_type: Mapped[str] = mapped_column(String(20), nullable=False)
    amount: Mapped[Decimal] = mapped_column(Numeric(14, 4), nullable=False)
    balance_after: Mapped[Decimal] = mapped_column(Numeric(14, 4), nullable=False)
    description: Mapped[str] = mapped_column(String(300), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    subscription: Mapped["CustomerSubscription"] = relationship(back_populates="ledger_entries")
