import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from content_studio.db.base import Base, TenantScopedMixin, TimestampMixin, UUIDPrimaryKeyMixin

# Phase 8's granular role catalog, extending the Phase 1 wildcard-only
# Owner role per this module's own forward-looking comments. A flat
# permission-string list (matching Role.permissions), not a parallel RBAC
# engine — "*" means everything, anything else is checked by exact string
# membership (see api/deps.py's require_permission()).
SYSTEM_ROLES: dict[str, list[str]] = {
    "Owner": ["*"],
    "Admin": [
        "workspace:manage", "membership:manage", "billing:manage", "content:manage",
        "campaign:manage", "analytics:view",
    ],
    "Editor": ["content:manage", "campaign:manage", "analytics:view"],
    "Client Viewer": ["content:view", "analytics:view"],
}

INVITATION_STATUSES = ("pending", "accepted", "revoked", "expired")
API_KEY_STATUSES = ("active", "revoked")


class Organization(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Root of the tenancy tree. An Organization is a customer account; it
    owns one or more Workspaces. Not itself tenant-scoped — it *is* the
    tenant."""

    __tablename__ = "organizations"

    name: Mapped[str] = mapped_column(String(200), nullable=False)
    slug: Mapped[str] = mapped_column(String(200), nullable=False, unique=True)
    is_agency: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    # White-label scaffold (Phase 8) — deliberately a handful of structured
    # fields, not a JSONB dump, matching BrandProfile's precedent. Applied
    # by the frontend as CSS custom-property overrides when present; a
    # workspace with no branding set falls back to the default theme.
    branding_product_name: Mapped[str | None] = mapped_column(String(200), nullable=True)
    branding_logo_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    branding_primary_color: Mapped[str | None] = mapped_column(String(7), nullable=True)

    workspaces: Mapped[list["Workspace"]] = relationship(back_populates="organization")
    roles: Mapped[list["Role"]] = relationship(back_populates="organization")


class Workspace(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """A working area within an Organization (e.g. one brand, one client for
    an agency). Content, campaigns, and assets are scoped to a Workspace."""

    __tablename__ = "workspaces"
    __table_args__ = (UniqueConstraint("organization_id", "slug", name="uq_workspace_org_slug"),)

    organization_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    slug: Mapped[str] = mapped_column(String(200), nullable=False)

    organization: Mapped["Organization"] = relationship(back_populates="workspaces")
    memberships: Mapped[list["Membership"]] = relationship(back_populates="workspace")
    brand_profiles: Mapped[list["BrandProfile"]] = relationship(back_populates="workspace")


class User(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """A person. Global identity, not tenant-scoped — a user reaches an
    Organization/Workspace through Membership rows, so one person can belong
    to multiple customer accounts (e.g. an agency contractor)."""

    __tablename__ = "users"

    email: Mapped[str] = mapped_column(String(320), nullable=False, unique=True, index=True)
    hashed_password: Mapped[str] = mapped_column(String(255), nullable=False)
    display_name: Mapped[str] = mapped_column(String(200), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    memberships: Mapped[list["Membership"]] = relationship(back_populates="user")
    refresh_tokens: Mapped[list["RefreshToken"]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )


class Role(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Org-scoped role. Permissions is a flat list of permission strings
    (e.g. "content:approve", "billing:manage") rather than a parallel RBAC
    system — matches the Phase 8 plan to extend this, not replace it, for
    agency/client roles."""

    __tablename__ = "roles"
    __table_args__ = (UniqueConstraint("organization_id", "name", name="uq_role_org_name"),)

    organization_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    permissions: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list)
    is_system_role: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    organization: Mapped["Organization"] = relationship(back_populates="roles")
    memberships: Mapped[list["Membership"]] = relationship(back_populates="role")


class Membership(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Binds a User to a Workspace with a Role. This is the row every
    Repository-layer query joins through to enforce tenant isolation."""

    __tablename__ = "memberships"
    __table_args__ = (
        UniqueConstraint("user_id", "workspace_id", name="uq_membership_user_workspace"),
    )

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    workspace_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False, index=True
    )
    role_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("roles.id", ondelete="RESTRICT"), nullable=False
    )

    user: Mapped["User"] = relationship(back_populates="memberships")
    workspace: Mapped["Workspace"] = relationship(back_populates="memberships")
    role: Mapped["Role"] = relationship(back_populates="memberships")


class BrandProfile(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Confirmed brand identity a workspace's content generation must honor.
    Structured fields for tone/colors/audiences plus a JSONB bag for
    genuinely variable extras — never a dumping ground for core fields."""

    __tablename__ = "brand_profiles"

    workspace_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    tone_description: Mapped[str | None] = mapped_column(Text, nullable=True)
    # What the workspace actually sells, e.g. "soy scented candles, room
    # diffusers, car diffusers, plant-based wax melts" — persistent context
    # fed into every product's generation prompt, entered once instead of
    # retyped per campaign.
    product_line_description: Mapped[str | None] = mapped_column(Text, nullable=True)
    vocabulary: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list)
    colors: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list)
    target_audiences: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list)
    default_ctas: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    workspace: Mapped["Workspace"] = relationship(back_populates="brand_profiles")
    rules: Mapped[list["BrandRule"]] = relationship(
        back_populates="brand_profile", cascade="all, delete-orphan"
    )


class BrandRule(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """A single enforceable rule (forbidden claim, required disclaimer,
    logo-usage constraint, etc.) checked as a quality gate during content
    generation (Phase 2)."""

    __tablename__ = "brand_rules"

    brand_profile_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("brand_profiles.id", ondelete="CASCADE"), nullable=False, index=True
    )
    rule_type: Mapped[str] = mapped_column(String(50), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    is_blocking: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    brand_profile: Mapped["BrandProfile"] = relationship(back_populates="rules")


class RefreshToken(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Postgres-authoritative refresh token — deliberately not stored in
    Redis, which is broker/coordination only per the hard architecture
    rule."""

    __tablename__ = "refresh_tokens"

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    token_hash: Mapped[str] = mapped_column(String(255), nullable=False, unique=True, index=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    user: Mapped["User"] = relationship(back_populates="refresh_tokens")


class Invitation(UUIDPrimaryKeyMixin, TimestampMixin, TenantScopedMixin, Base):
    """A pending email invitation to a workspace — the Phase 8 extension
    the Phase 1 IdentityService.add_member() docstring explicitly flagged
    ('no email-invitation flow / pending-invite entity yet'). Works for
    both an existing user (accept immediately binds a Membership) and
    someone without an account yet (they sign up, then accept). The token
    is single-use and never stored in plaintext, same discipline as
    RefreshToken."""

    __tablename__ = "invitations"
    __table_args__ = (
        ForeignKeyConstraint(
            ["organization_id"], ["organizations.id"], ondelete="CASCADE",
            name="fk_invitations_organization_id_organizations",
        ),
        CheckConstraint(f"status in {INVITATION_STATUSES}", name="ck_invitation_status"),
    )

    workspace_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False, index=True
    )
    email: Mapped[str] = mapped_column(String(320), nullable=False, index=True)
    role_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("roles.id", ondelete="RESTRICT"), nullable=False
    )
    invited_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    token_hash: Mapped[str] = mapped_column(String(64), nullable=False, unique=True, index=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="pending")
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    accepted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class ApiKey(UUIDPrimaryKeyMixin, TimestampMixin, TenantScopedMixin, Base):
    """A workspace-scoped public-API credential. Only the SHA-256 hash is
    ever persisted — the raw key is shown to the user exactly once, at
    creation, same discipline as RefreshToken/Invitation. Scoped by
    `scopes` (same flat permission-string shape as Role.permissions) and
    rate-limited per key via Redis (see rate_limit.py) — Redis holds only
    the ephemeral request counters, never the key itself."""

    __tablename__ = "api_keys"
    __table_args__ = (
        ForeignKeyConstraint(
            ["organization_id"], ["organizations.id"], ondelete="CASCADE",
            name="fk_api_keys_organization_id_organizations",
        ),
        CheckConstraint(f"status in {API_KEY_STATUSES}", name="ck_api_key_status"),
    )

    workspace_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False, index=True
    )
    created_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    key_prefix: Mapped[str] = mapped_column(String(20), nullable=False)
    key_hash: Mapped[str] = mapped_column(String(64), nullable=False, unique=True, index=True)
    scopes: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="active")
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
