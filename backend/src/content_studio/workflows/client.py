from temporalio.client import Client

from content_studio.config import get_settings

_client: Client | None = None


async def get_temporal_client() -> Client:
    """Lazily-created, process-wide Temporal client. Safe to cache (unlike
    the async DB engine pattern that bit us in tests/conftest.py) because
    temporalio's Client is explicitly designed to be a long-lived singleton
    shared across the whole process."""
    global _client
    if _client is None:
        settings = get_settings()
        _client = await Client.connect(settings.temporal_target, namespace=settings.temporal_namespace)
    return _client
