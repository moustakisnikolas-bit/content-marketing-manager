import uuid
from datetime import UTC, datetime, timedelta

from content_studio.ports.social_platform import (
    CapabilityResult,
    ConnectableAccount,
    OAuthToken,
    PublishResult,
    RecentPost,
)

_STUB_RECENT_CAPTIONS = [
    "New arrivals just dropped — link in bio!",
    "Behind the scenes making this week's batch.",
    "Customer favorite, back in stock today.",
]

# Realistic-but-simulated capability differences per platform, so the
# capability-resolution architecture (never hardcoded in application code,
# always asked of the adapter per connection) has something meaningful to
# prove: two connections to different platforms genuinely resolve
# different capabilities. Real values come from each platform's Graph/Data
# API once a developer app is registered and reviewed — deferred, see
# docs/adr/ (Phase 3 follow-up), not fabricated as if verified today.
_PLATFORM_CAPABILITIES: dict[str, dict[str, str | None]] = {
    "facebook": {"direct_publish_text": None, "direct_publish_image": None, "direct_publish_video": None},
    "instagram": {
        "direct_publish_image": None,
        "direct_publish_video": None,
        "direct_publish_story": None,
        "direct_publish_text": "Instagram has no text-only post type",
    },
    "tiktok": {
        "direct_publish_video": None,
        "direct_publish_text": "TikTok requires video content",
        "direct_publish_image": "TikTok requires video content",
    },
    "youtube": {
        "direct_publish_video": None,
        "direct_publish_text": "YouTube requires video content",
        "direct_publish_image": "YouTube requires video content",
    },
}


class StubSocialPlatformAdapter:
    """Dev-mode fallback used when no real OAuth app is configured for a
    platform (see Settings.social_oauth_client_id). Simulates a complete,
    self-contained OAuth handshake and publish flow so the connect ->
    schedule -> approve -> publish -> reconcile lifecycle is fully
    testable without a live developer-portal registration."""

    def __init__(self, platform: str) -> None:
        self._platform = platform

    def get_authorization_url(self, *, state: str) -> str:
        return f"https://stub-oauth.local/{self._platform}/authorize?state={state}"

    async def exchange_code_for_token(self, *, code: str) -> OAuthToken:
        account_id = f"stub-{self._platform}-{uuid.uuid4().hex[:8]}"
        return OAuthToken(
            access_token=f"stub-access-token-{uuid.uuid4().hex}",
            refresh_token=f"stub-refresh-token-{uuid.uuid4().hex}",
            external_account_id=account_id,
            external_account_name=f"Demo {self._platform.title()} Account",
            scopes=["publish_content", "read_insights"],
        )

    async def list_connectable_accounts(self, *, access_token: str) -> list[ConnectableAccount]:
        # The stub's exchange_code_for_token() always fabricates exactly
        # one account — mirror that here so it's always the "already
        # resolved, no picker needed" single-item case.
        account_id = f"stub-{self._platform}-{uuid.uuid4().hex[:8]}"
        return [
            ConnectableAccount(
                external_account_id=account_id, external_account_name=f"Demo {self._platform.title()} Account"
            )
        ]

    async def resolve_account_token(self, *, access_token: str, external_account_id: str) -> OAuthToken:
        return OAuthToken(
            access_token=f"stub-access-token-{uuid.uuid4().hex}",
            refresh_token=f"stub-refresh-token-{uuid.uuid4().hex}",
            external_account_id=external_account_id,
            external_account_name=f"Demo {self._platform.title()} Account",
            scopes=["publish_content", "read_insights"],
        )

    async def resolve_capabilities(self, *, access_token: str) -> list[CapabilityResult]:
        capabilities = _PLATFORM_CAPABILITIES.get(self._platform, {})
        return [
            CapabilityResult(capability=name, is_available=reason is None, reason=reason)
            for name, reason in capabilities.items()
        ]

    async def publish_text(self, *, access_token: str, external_account_id: str, text: str) -> PublishResult:
        return PublishResult(external_post_id=f"stub-post-{uuid.uuid4().hex[:12]}")

    async def publish_image(
        self, *, access_token: str, external_account_id: str, text: str, image_url: str
    ) -> PublishResult:
        return PublishResult(external_post_id=f"stub-post-{uuid.uuid4().hex[:12]}")

    async def publish_story(
        self, *, access_token: str, external_account_id: str, image_url: str
    ) -> PublishResult:
        return PublishResult(external_post_id=f"stub-story-{uuid.uuid4().hex[:12]}")

    async def get_post_status(self, *, access_token: str, external_post_id: str) -> str:
        return "published"

    async def get_post_metrics(self, *, access_token: str, external_post_id: str) -> dict:
        # Deterministic-but-varied: seeded by the post id so repeated polls of
        # the same post return a stable-shaped but slowly "growing" payload,
        # without a database of its own. Field names are deliberately
        # provider-flavored (not pre-normalized) to exercise the dual-storage
        # rule downstream in the analytics module.
        seed = int(uuid.uuid5(uuid.NAMESPACE_URL, f"{self._platform}:{external_post_id}").hex, 16)
        impressions = 200 + (seed % 4800)
        likes = impressions // (20 + (seed % 10))
        comments = likes // (5 + (seed % 5))
        shares = likes // (8 + (seed % 6))
        clicks = impressions // (15 + (seed % 20))
        if self._platform == "youtube":
            return {
                "views": impressions,
                "likes": likes,
                "comments": comments,
                "shares": shares,
                "averageViewDurationSeconds": 20 + (seed % 90),
            }
        return {
            "impressions": impressions,
            "likes": likes,
            "comments": comments,
            "shares": shares,
            "link_clicks": clicks,
        }

    async def list_recent_posts(
        self, *, access_token: str, external_account_id: str, limit: int = 5
    ) -> list[RecentPost]:
        now = datetime.now(UTC)
        return [
            RecentPost(
                external_post_id=f"stub-post-{uuid.uuid5(uuid.NAMESPACE_URL, f'{external_account_id}:{i}').hex[:12]}",
                caption=_STUB_RECENT_CAPTIONS[i % len(_STUB_RECENT_CAPTIONS)],
                posted_at=now - timedelta(days=i * 3),
            )
            for i in range(min(limit, len(_STUB_RECENT_CAPTIONS)))
        ]
