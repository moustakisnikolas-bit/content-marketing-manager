import asyncio
from urllib.parse import urlencode

import httpx

from content_studio.config import Settings
from content_studio.ports.social_platform import (
    CapabilityResult,
    ConnectableAccount,
    OAuthToken,
    PublishResult,
)

_GRAPH_API_BASE = "https://graph.facebook.com/v21.0"
_OAUTH_DIALOG_BASE = "https://www.facebook.com/v21.0/dialog/oauth"
# All requested up front regardless of which platform (facebook/instagram)
# the user is connecting — usable by app admins/testers without Meta App
# Review, which is the whole point for a personal/single-shop deployment.
# (Confirmed live 2026-08-27: a temporary test stripped to just
# public_profile hit the exact same "Login is currently unavailable...
# updating additional details" error, ruling out scope count/sensitivity
# as the cause — see windows-dev-gotchas / woocommerce-plugin memory.)
_REQUESTED_SCOPES = (
    "pages_show_list",
    "pages_read_engagement",
    "pages_manage_posts",
    "instagram_basic",
    "instagram_content_publish",
)
_TIMEOUT = httpx.Timeout(connect=10, read=30, write=10, pool=10)
_POLL_INTERVAL_SECONDS = 2
_MAX_POLL_ATTEMPTS = 30  # ~60s ceiling for a container to finish processing


class MetaGraphAdapter:
    """Real Facebook/Instagram Graph API adapter. One instance per
    platform ("facebook" or "instagram"), matching the factory's existing
    per-platform construction. Facebook publishes directly to a Page;
    Instagram publishes to the Business Account linked to a Page, resolved
    in resolve_account_token() — both share the same OAuth app/user token,
    which is why get_authorization_url()/exchange_code_for_token() don't
    branch on platform at all."""

    def __init__(self, settings: Settings, platform: str) -> None:
        self._platform = platform
        self._client_id = settings.social_oauth_client_id
        self._client_secret = settings.social_oauth_client_secret
        self._redirect_uri = settings.social_oauth_redirect_base_url

    def get_authorization_url(self, *, state: str) -> str:
        params = {
            "client_id": self._client_id,
            "redirect_uri": self._redirect_uri,
            "state": state,
            "scope": ",".join(_REQUESTED_SCOPES),
        }
        return f"{_OAUTH_DIALOG_BASE}?{urlencode(params)}"

    async def exchange_code_for_token(self, *, code: str) -> OAuthToken:
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            short_lived = await client.get(
                f"{_GRAPH_API_BASE}/oauth/access_token",
                params={
                    "client_id": self._client_id,
                    "client_secret": self._client_secret,
                    "redirect_uri": self._redirect_uri,
                    "code": code,
                },
            )
            short_lived.raise_for_status()

            # Exchange for a long-lived (~60 day) user token — the short-lived
            # one from the redirect expires in ~1-2h, too short to be useful
            # once a PlatformConnection is persisted.
            long_lived = await client.get(
                f"{_GRAPH_API_BASE}/oauth/access_token",
                params={
                    "grant_type": "fb_exchange_token",
                    "client_id": self._client_id,
                    "client_secret": self._client_secret,
                    "fb_exchange_token": short_lived.json()["access_token"],
                },
            )
            long_lived.raise_for_status()
            user_token = long_lived.json()["access_token"]

            me = await client.get(f"{_GRAPH_API_BASE}/me", params={"fields": "id,name", "access_token": user_token})
            me.raise_for_status()
            me_data = me.json()

        return OAuthToken(
            access_token=user_token,
            refresh_token=None,
            external_account_id=me_data["id"],
            external_account_name=me_data["name"],
            scopes=list(_REQUESTED_SCOPES),
        )

    async def list_connectable_accounts(self, *, access_token: str) -> list[ConnectableAccount]:
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            response = await client.get(f"{_GRAPH_API_BASE}/me/accounts", params={"access_token": access_token})
            response.raise_for_status()
        return [
            ConnectableAccount(external_account_id=page["id"], external_account_name=page["name"])
            for page in response.json().get("data", [])
        ]

    async def resolve_account_token(self, *, access_token: str, external_account_id: str) -> OAuthToken:
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            page_response = await client.get(
                f"{_GRAPH_API_BASE}/{external_account_id}",
                params={"fields": "access_token,name", "access_token": access_token},
            )
            page_response.raise_for_status()
            page_data = page_response.json()
            page_token = page_data["access_token"]

            if self._platform != "instagram":
                return OAuthToken(
                    access_token=page_token,
                    refresh_token=None,
                    external_account_id=external_account_id,
                    external_account_name=page_data["name"],
                    scopes=list(_REQUESTED_SCOPES),
                )

            ig_response = await client.get(
                f"{_GRAPH_API_BASE}/{external_account_id}",
                params={"fields": "instagram_business_account", "access_token": page_token},
            )
            ig_response.raise_for_status()
            ig_account = ig_response.json().get("instagram_business_account")
            if ig_account is None:
                raise RuntimeError(
                    f"Page {page_data['name']!r} has no linked Instagram Business Account — "
                    "link one in Meta Business Suite before connecting Instagram here."
                )
            return OAuthToken(
                access_token=page_token,  # Instagram publishing uses the Page's token, not a separate IG token.
                refresh_token=None,
                external_account_id=ig_account["id"],
                external_account_name=page_data["name"],
                scopes=list(_REQUESTED_SCOPES),
            )

    async def resolve_capabilities(self, *, access_token: str) -> list[CapabilityResult]:
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            response = await client.get(f"{_GRAPH_API_BASE}/me/permissions", params={"access_token": access_token})
            response.raise_for_status()
        granted = {p["permission"] for p in response.json().get("data", []) if p.get("status") == "granted"}

        if self._platform == "instagram":
            has_publish = {"instagram_basic", "instagram_content_publish"} <= granted
            reason = None if has_publish else "Missing instagram_basic/instagram_content_publish permission"
            return [
                CapabilityResult(capability="direct_publish_image", is_available=has_publish, reason=reason),
                CapabilityResult(capability="direct_publish_story", is_available=has_publish, reason=reason),
            ]

        has_publish = "pages_manage_posts" in granted
        reason = None if has_publish else "Missing pages_manage_posts permission"
        return [
            CapabilityResult(capability="direct_publish_text", is_available=has_publish, reason=reason),
            CapabilityResult(capability="direct_publish_image", is_available=has_publish, reason=reason),
        ]

    async def publish_text(self, *, access_token: str, external_account_id: str, text: str) -> PublishResult:
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            response = await client.post(
                f"{_GRAPH_API_BASE}/{external_account_id}/feed",
                data={"message": text, "access_token": access_token},
            )
            response.raise_for_status()
            return PublishResult(external_post_id=response.json()["id"])

    async def publish_image(
        self, *, access_token: str, external_account_id: str, text: str, image_url: str
    ) -> PublishResult:
        if self._platform == "instagram":
            return await self._publish_instagram_media(
                access_token=access_token, external_account_id=external_account_id, image_url=image_url,
                caption=text, media_type=None,
            )
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            response = await client.post(
                f"{_GRAPH_API_BASE}/{external_account_id}/photos",
                data={"url": image_url, "caption": text, "access_token": access_token},
            )
            response.raise_for_status()
            body = response.json()
            return PublishResult(external_post_id=body.get("post_id", body["id"]))

    async def publish_story(
        self, *, access_token: str, external_account_id: str, image_url: str
    ) -> PublishResult:
        if self._platform != "instagram":
            raise NotImplementedError("Facebook Page Stories aren't supported by this adapter")
        return await self._publish_instagram_media(
            access_token=access_token, external_account_id=external_account_id, image_url=image_url,
            caption=None, media_type="STORIES",
        )

    async def _publish_instagram_media(
        self, *, access_token: str, external_account_id: str, image_url: str, caption: str | None,
        media_type: str | None,
    ) -> PublishResult:
        # Two-step container->publish flow — required by Instagram's
        # Content Publishing API for every media type. Images usually
        # finish near-instantly, but there's no documented guarantee, so
        # this polls the same way ai_image/replicate.py polls a prediction.
        create_params: dict[str, str] = {"image_url": image_url, "access_token": access_token}
        if caption:
            create_params["caption"] = caption
        if media_type:
            create_params["media_type"] = media_type

        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            create_response = await client.post(f"{_GRAPH_API_BASE}/{external_account_id}/media", data=create_params)
            create_response.raise_for_status()
            container_id = create_response.json()["id"]

            await self._await_container_ready(client, container_id=container_id, access_token=access_token)

            publish_response = await client.post(
                f"{_GRAPH_API_BASE}/{external_account_id}/media_publish",
                data={"creation_id": container_id, "access_token": access_token},
            )
            publish_response.raise_for_status()
            return PublishResult(external_post_id=publish_response.json()["id"])

    async def _await_container_ready(self, client: httpx.AsyncClient, *, container_id: str, access_token: str) -> None:
        for _ in range(_MAX_POLL_ATTEMPTS):
            status_response = await client.get(
                f"{_GRAPH_API_BASE}/{container_id}", params={"fields": "status_code", "access_token": access_token}
            )
            status_response.raise_for_status()
            status_code = status_response.json().get("status_code")
            if status_code == "FINISHED":
                return
            if status_code == "ERROR":
                raise RuntimeError(f"Instagram media container {container_id} failed processing")
            await asyncio.sleep(_POLL_INTERVAL_SECONDS)
        raise TimeoutError(f"Instagram media container {container_id} did not finish processing in time")

    async def get_post_status(self, *, access_token: str, external_post_id: str) -> str:
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            response = await client.get(
                f"{_GRAPH_API_BASE}/{external_post_id}", params={"fields": "id", "access_token": access_token}
            )
        return "published" if response.status_code == 200 else f"error:{response.status_code}"

    async def get_post_metrics(self, *, access_token: str, external_post_id: str) -> dict:
        # Field names mapped onto the same shape the stub already uses
        # (impressions/likes/comments/shares/link_clicks) so
        # MetricsIngestionService._RAW_FIELD_TO_METRIC needs no changes —
        # best-effort: Graph API insights metric availability varies by
        # object type/API version, so a partial/empty result here is
        # expected sometimes, not necessarily a bug.
        metric_names = "post_impressions,post_engaged_users,post_clicks" if self._platform != "instagram" else "impressions,reach,saved"
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            response = await client.get(
                f"{_GRAPH_API_BASE}/{external_post_id}/insights",
                params={"metric": metric_names, "access_token": access_token},
            )
            if response.status_code != 200:
                return {}
        values = {row["name"]: row["values"][0]["value"] for row in response.json().get("data", []) if row.get("values")}
        if self._platform == "instagram":
            return {
                "impressions": values.get("impressions", 0),
                "likes": 0,
                "comments": 0,
                "shares": values.get("saved", 0),
                "link_clicks": 0,
            }
        return {
            "impressions": values.get("post_impressions", 0),
            "likes": values.get("post_engaged_users", 0),
            "comments": 0,
            "shares": 0,
            "link_clicks": values.get("post_clicks", 0),
        }
