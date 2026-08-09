from typing import Protocol


class ObjectStoragePort(Protocol):
    """Provider-neutral port for private object storage, per
    21_PROVIDER_STRATEGY_AND_COSTS.md. Application Services depend on this
    interface only — never on a concrete storage SDK directly."""

    async def put_object(self, *, key: str, data: bytes, content_type: str) -> None: ...

    async def get_presigned_url(self, *, key: str, expires_in_seconds: int = 3600) -> str: ...

    async def delete_object(self, *, key: str) -> None: ...
