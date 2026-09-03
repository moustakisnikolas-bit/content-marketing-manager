from dataclasses import dataclass
from datetime import datetime
from typing import Protocol


@dataclass(frozen=True)
class OAuthToken:
    access_token: str
    refresh_token: str | None
    external_account_id: str
    external_account_name: str
    scopes: list[str]


@dataclass(frozen=True)
class CapabilityResult:
    capability: str
    is_available: bool
    reason: str | None = None


@dataclass(frozen=True)
class PublishResult:
    external_post_id: str


@dataclass(frozen=True)
class ConnectableAccount:
    external_account_id: str
    external_account_name: str


@dataclass(frozen=True)
class RecentPost:
    external_post_id: str
    caption: str | None
    posted_at: datetime | None


class SocialPlatformPort(Protocol):
    """Provider-neutral port for a connected social platform. One concrete
    adapter per platform (Facebook Pages, Instagram Professional, TikTok,
    YouTube/Shorts — the Phase 3 commitment from
    10_SOCIAL_PUBLISHING_MODULE.md). Capabilities are always resolved
    through resolve_capabilities(), never hardcoded by the application —
    'enable a capability only when backed by official API + connected
    account + granted scopes + app approval + current restrictions.'"""

    def get_authorization_url(self, *, state: str) -> str: ...

    async def exchange_code_for_token(self, *, code: str) -> OAuthToken:
        """Exchanges an OAuth code for a *user-level* token. For platforms
        with an implicit single publishing account (most of them, and the
        stub), the returned OAuthToken.external_account_id is already the
        final account to publish with. Meta's OAuth grants access to every
        Facebook Page the user manages, so its adapter returns a token
        representing the user, not yet a specific Page — see
        list_connectable_accounts()/resolve_account_token()."""
        ...

    async def list_connectable_accounts(self, *, access_token: str) -> list[ConnectableAccount]:
        """Accounts the just-exchanged user-level token could publish as.
        Most platforms (and the stub) have exactly one implicit account,
        matching exchange_code_for_token()'s own external_account_id/name —
        callers should treat a single-item result as "already resolved,
        no picker needed." Meta returns one entry per Facebook Page the
        user manages."""
        ...

    async def resolve_account_token(self, *, access_token: str, external_account_id: str) -> OAuthToken:
        """Given the user-level access_token and a choice from
        list_connectable_accounts(), resolves the account-scoped token to
        actually publish with (e.g. a Facebook Page access token, and for
        Instagram, the linked Instagram Business Account id as
        external_account_id instead of the Page id)."""
        ...

    async def resolve_capabilities(self, *, access_token: str) -> list[CapabilityResult]: ...

    async def publish_text(self, *, access_token: str, external_account_id: str, text: str) -> PublishResult: ...

    async def publish_image(
        self, *, access_token: str, external_account_id: str, text: str, image_url: str
    ) -> PublishResult:
        """image_url must be publicly fetchable, not e.g. a Docker-internal
        object storage address — Instagram's Graph API creates media
        containers by having Meta's own servers fetch the URL server-side,
        it has no raw-bytes-upload path for images (only Facebook's /photos
        endpoint does, but it also accepts a url= param, so this port
        standardizes on URLs for both rather than two different shapes).
        The caller (PublishingService.dispatch_publish) gets this from
        ObjectStoragePort.get_presigned_url() — on a real deployment that
        needs to actually be internet-reachable, which is an operational
        requirement of the object storage endpoint's public exposure, not
        something this port can enforce."""
        ...

    async def publish_story(
        self, *, access_token: str, external_account_id: str, image_url: str
    ) -> PublishResult:
        """Instagram Stories only — Facebook Page Stories aren't supported
        by this port (inconsistent Graph API support, deliberately kept
        out of scope). Platforms with no Stories concept (the stub's
        non-Instagram platforms) can raise NotImplementedError."""
        ...

    async def get_post_status(self, *, access_token: str, external_post_id: str) -> str: ...

    async def delete_post(self, *, access_token: str, external_post_id: str) -> None:
        """Removes an already-published post/media from the platform
        itself, not just this app's own record of it — a real, irreversible
        action on the connected account. Implementations should raise on
        failure (a 404 from the platform is not swallowed as success)."""
        ...

    async def get_post_metrics(self, *, access_token: str, external_post_id: str) -> dict:
        """Returns the provider's raw, native metric payload for a post
        (e.g. {'impressions': 1523, 'likes': 42, ...}) — field names and
        shape are provider-specific, per 11_ANALYTICS_AND_OPTIMIZATION.md's
        dual-storage rule. Normalization onto MetricDefinition happens in
        the analytics module, not here."""
        ...

    async def list_recent_posts(
        self, *, access_token: str, external_account_id: str, limit: int = 5
    ) -> list[RecentPost]:
        """Already-published posts/media for this account, most recent
        first — used as a style/tone reference for new generation, not for
        publishing or metrics. Best-effort: implementations should return
        an empty list rather than raise on any provider-side failure, since
        callers treat this purely as an optional quality boost."""
        ...
