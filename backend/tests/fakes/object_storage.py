class FakeObjectStorage:
    """In-memory ObjectStoragePort implementation. Satisfies the same
    Protocol as SeaweedFSObjectStorage — used both in unit tests and as the
    default local adapter until a real bucket is configured."""

    def __init__(self) -> None:
        self.objects: dict[str, tuple[bytes, str]] = {}
        self.deleted_keys: list[str] = []

    async def put_object(self, *, key: str, data: bytes, content_type: str) -> None:
        self.objects[key] = (data, content_type)

    async def get_presigned_url(self, *, key: str, expires_in_seconds: int = 3600) -> str:
        if key not in self.objects:
            raise KeyError(key)
        return f"fake://{key}?expires_in={expires_in_seconds}"

    async def delete_object(self, *, key: str) -> None:
        self.objects.pop(key, None)
        self.deleted_keys.append(key)
