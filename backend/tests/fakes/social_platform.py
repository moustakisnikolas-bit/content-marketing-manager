import uuid

from content_studio.ports.social_platform import (
    CapabilityResult,
    ConnectableAccount,
    OAuthToken,
    PublishResult,
    RecentPost,
)


class FakeSocialPlatform:
    """In-memory SocialPlatformPort implementation with configurable
    capabilities and failure injection, for exercising the
    capability-resolution and publish-failure paths deterministically."""

    def __init__(
        self,
        *,
        capabilities: list[CapabilityResult] | None = None,
        publish_should_fail: bool = False,
        post_status: str = "published",
        post_metrics: dict | None = None,
        accounts: list[ConnectableAccount] | None = None,
        recent_posts: list[RecentPost] | None = None,
    ) -> None:
        self.capabilities = capabilities or [
            CapabilityResult(capability="direct_publish_text", is_available=True),
            CapabilityResult(capability="direct_publish_image", is_available=True),
        ]
        self.publish_should_fail = publish_should_fail
        self.post_status = post_status
        self.post_metrics = post_metrics or {
            "impressions": 1000,
            "likes": 50,
            "comments": 5,
            "shares": 3,
            "link_clicks": 20,
        }
        self.accounts = accounts or [
            ConnectableAccount(external_account_id=f"fake-account-{uuid.uuid4().hex[:8]}", external_account_name="Fake Account")
        ]
        self.recent_posts = recent_posts or []
        self.published_calls: list[dict] = []

    def get_authorization_url(self, *, state: str) -> str:
        return f"https://fake-oauth.test/authorize?state={state}"

    async def exchange_code_for_token(self, *, code: str) -> OAuthToken:
        return OAuthToken(
            access_token="fake-access-token",
            refresh_token="fake-refresh-token",
            external_account_id=self.accounts[0].external_account_id,
            external_account_name=self.accounts[0].external_account_name,
            scopes=["publish_content"],
        )

    async def list_connectable_accounts(self, *, access_token: str) -> list[ConnectableAccount]:
        return self.accounts

    async def resolve_account_token(self, *, access_token: str, external_account_id: str) -> OAuthToken:
        account = next(a for a in self.accounts if a.external_account_id == external_account_id)
        return OAuthToken(
            access_token=f"fake-access-token-{account.external_account_id}",
            refresh_token="fake-refresh-token",
            external_account_id=account.external_account_id,
            external_account_name=account.external_account_name,
            scopes=["publish_content"],
        )

    async def resolve_capabilities(self, *, access_token: str) -> list[CapabilityResult]:
        return self.capabilities

    async def publish_text(self, *, access_token: str, external_account_id: str, text: str) -> PublishResult:
        self.published_calls.append({"kind": "text", "text": text})
        if self.publish_should_fail:
            raise RuntimeError("simulated platform publish failure")
        return PublishResult(external_post_id=f"fake-post-{uuid.uuid4().hex[:12]}")

    async def publish_image(
        self, *, access_token: str, external_account_id: str, text: str, image_url: str
    ) -> PublishResult:
        self.published_calls.append({"kind": "image", "text": text, "image_url": image_url})
        if self.publish_should_fail:
            raise RuntimeError("simulated platform publish failure")
        return PublishResult(external_post_id=f"fake-post-{uuid.uuid4().hex[:12]}")

    async def publish_story(
        self, *, access_token: str, external_account_id: str, image_url: str
    ) -> PublishResult:
        self.published_calls.append({"kind": "story", "image_url": image_url})
        if self.publish_should_fail:
            raise RuntimeError("simulated platform publish failure")
        return PublishResult(external_post_id=f"fake-story-{uuid.uuid4().hex[:12]}")

    async def get_post_status(self, *, access_token: str, external_post_id: str) -> str:
        return self.post_status

    async def get_post_metrics(self, *, access_token: str, external_post_id: str) -> dict:
        return self.post_metrics

    async def list_recent_posts(
        self, *, access_token: str, external_account_id: str, limit: int = 5
    ) -> list[RecentPost]:
        return self.recent_posts[:limit]
