from content_studio.config import Settings
from content_studio.ports.ai_audio import AIAudioPort
from content_studio.ports.ai_image import AIImagePort
from content_studio.ports.ai_text import AITextPort
from content_studio.ports.policy import PolicyPort
from content_studio.ports.secrets import SecretsPort
from content_studio.ports.social_platform import SocialPlatformPort
from content_studio.ports.store_connector import StoreConnectorPort

# Shared between the FastAPI process (api/deps.py) and the Temporal worker
# process (workflows/*.py activities) so both pick the same concrete
# adapter for a given Settings — real provider if a key is configured,
# stub otherwise. Neither entry point imports the other's framework
# (FastAPI DI vs Temporal activities), so this lives independent of both.


def get_ai_text_adapter(settings: Settings) -> AITextPort:
    if settings.ai_text_api_key:
        from content_studio.adapters.ai_text.litellm import LiteLLMTextAdapter

        return LiteLLMTextAdapter(settings)
    from content_studio.adapters.ai_text.stub import StubAITextAdapter

    return StubAITextAdapter()


def get_ai_image_adapter(settings: Settings) -> AIImagePort:
    if settings.replicate_api_token:
        from content_studio.adapters.ai_image.replicate import ReplicateImageAdapter

        return ReplicateImageAdapter(settings)
    from content_studio.adapters.ai_image.stub import StubAIImageAdapter

    return StubAIImageAdapter()


def get_ai_audio_adapter(settings: Settings) -> AIAudioPort:
    if settings.replicate_api_token:
        from content_studio.adapters.ai_audio.replicate import ReplicateAudioAdapter

        return ReplicateAudioAdapter(settings)
    from content_studio.adapters.ai_audio.stub import StubAIAudioAdapter

    return StubAIAudioAdapter()


def get_secrets_adapter(settings: Settings) -> SecretsPort:
    # OpenBao is treated as always-available core infra (like Postgres or
    # SeaweedFS), not an optional paid provider — no stub fallback.
    from content_studio.adapters.secrets.openbao import OpenBaoSecretsAdapter

    return OpenBaoSecretsAdapter(settings)


def get_policy_adapter(settings: Settings) -> PolicyPort:
    # OPA is core infra (like Postgres/SeaweedFS/OpenBao), not an optional
    # paid provider — no stub fallback.
    from content_studio.adapters.policy.opa import OPAPolicyAdapter

    return OPAPolicyAdapter(settings)


def get_social_platform_adapter(settings: Settings, platform: str) -> SocialPlatformPort:
    # Real Meta (Facebook/Instagram) adapter once an app is configured —
    # same "empty client_id means stub" fallback pattern as the AI
    # adapters above. TikTok/YouTube have no real adapter yet (never asked
    # for), so they always get the stub regardless of social_oauth_client_id.
    if settings.social_oauth_client_id and platform in ("facebook", "instagram"):
        from content_studio.adapters.social_platform.meta import MetaGraphAdapter

        return MetaGraphAdapter(settings, platform)
    from content_studio.adapters.social_platform.stub import StubSocialPlatformAdapter

    return StubSocialPlatformAdapter(platform)


def get_store_connector_adapter(settings: Settings, platform: str) -> StoreConnectorPort:
    # WooCommerce credentials are per-connection (a Consumer Key/Secret
    # pasted per store via connect_with_credentials), not app-level config,
    # so unlike the other adapters this doesn't branch on a Settings value
    # — the real adapter is always used for this platform. Shopify has no
    # real adapter yet (never asked for), so it always gets the stub.
    if platform == "woocommerce":
        from content_studio.adapters.store_connector.woocommerce import WooCommerceAdapter

        return WooCommerceAdapter(settings)
    from content_studio.adapters.store_connector.stub import StubStoreConnectorAdapter

    return StubStoreConnectorAdapter(platform)
