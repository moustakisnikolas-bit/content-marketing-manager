from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_prefix="CS_", extra="ignore")

    database_url: str = "postgresql+asyncpg://content_studio:content_studio_dev@localhost:5432/content_studio"

    # This backend's own publicly-reachable base URL — used to build
    # callback URLs handed to third parties (e.g. the WooCommerce webhook
    # delivery_url registered via adapters/store_connector/woocommerce.py).
    # Distinct from social_oauth_redirect_base_url/CS_SOCIAL_OAUTH_REDIRECT_BASE_URL,
    # which points at a frontend route, not this API directly.
    public_api_base_url: str = "http://localhost:8000/api/v1"

    jwt_secret: str = "dev-only-change-me"
    jwt_algorithm: str = "HS256"
    access_token_ttl_minutes: int = 15
    refresh_token_ttl_days: int = 30

    # Cache/coordination only, per the hard architecture rule — Redis never
    # holds authoritative business data (PostgreSQL is sole authoritative
    # store). First real use: Phase 8's public-API rate limiter.
    # Explicit 127.0.0.1, not "localhost": redis.asyncio's connection path
    # times out resolving "localhost" on this Windows dev setup even
    # though every other client (sync redis-py, browsers, curl) resolves
    # it fine — see windows_dev_gotchas.md.
    redis_url: str = "redis://127.0.0.1:6379/0"

    object_storage_endpoint: str = "http://localhost:8333"
    object_storage_bucket: str = "content-studio-assets"
    object_storage_access_key: str = "dev"
    object_storage_secret_key: str = "dev-secret"

    temporal_target: str = "localhost:7233"
    temporal_namespace: str = "default"
    temporal_task_queue: str = "content-studio"

    opa_url: str = "http://localhost:8181"

    otel_exporter_endpoint: str = "http://localhost:4317"
    environment: str = "development"

    # AI generation adapters (docs/adr/0003). ai_text_base_url defaults to
    # OpenRouter's own OpenAI-compatible endpoint; point it at a local
    # LiteLLM Proxy instead (e.g. http://localhost:4000/v1) once that
    # gateway is deployed, without touching adapter code. Empty API keys
    # mean "no real provider configured" — deps.py falls back to the fake
    # adapters in that case so the app runs out of the box without paid
    # keys.
    ai_text_base_url: str = "https://openrouter.ai/api/v1"
    ai_text_api_key: str = ""
    ai_text_default_model: str = "openai/gpt-4o-mini"

    replicate_api_token: str = ""
    ai_image_default_model: str = "black-forest-labs/flux-schnell"
    # Kokoro-82M (Apache-2.0, commercial-safe) — the TTS model this
    # project's own OSS stack plan recommended; hosted via Replicate for
    # Phase-2-style zero-GPU-ops generation, same pattern as ai_image.
    ai_audio_default_model: str = "jaaari/kokoro-82m"

    openbao_url: str = "http://localhost:8200"
    openbao_token: str = "dev-root-token"
    openbao_secret_mount: str = "secret"

    # Social platform adapters (Phase 3). Real Facebook/Instagram/TikTok/
    # YouTube apps each need a live developer-portal registration this dev
    # environment doesn't have — empty client_id means "use the stub
    # adapter," same fallback pattern as the AI ports in Phase 2.
    social_oauth_client_id: str = ""
    social_oauth_client_secret: str = ""
    # Points at the frontend's own /oauth/callback route (see
    # apps/web/src/app/(app)/oauth/callback/page.tsx), not this backend
    # directly — that page reads code/state off the URL and calls this
    # API's /publishing/oauth/callback itself, same as the stub-simulated
    # flow already did before a real Meta adapter existed.
    social_oauth_redirect_base_url: str = "http://localhost:3000/oauth/callback"

    # Store connector adapters (Phase 6). Real WooCommerce/Shopify apps each
    # need a live store + registered app this dev environment doesn't have —
    # empty client_id means "use the stub adapter," same fallback pattern as
    # the social platform adapters.
    store_oauth_client_id: str = ""
    store_oauth_client_secret: str = ""
    # Inbound webhooks are unauthenticated except by HMAC signature, so a
    # hard body-size cap guards against a malicious/misbehaving sender
    # before any JSON parsing happens.
    max_webhook_body_bytes: int = 1_000_000


@lru_cache
def get_settings() -> Settings:
    return Settings()
