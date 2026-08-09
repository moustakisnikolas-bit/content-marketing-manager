import uuid


class FakeSecrets:
    """In-memory SecretsPort implementation."""

    def __init__(self) -> None:
        self.store: dict[str, str] = {}

    async def seal(self, *, value: str) -> str:
        reference = f"fake-secret/{uuid.uuid4()}"
        self.store[reference] = value
        return reference

    async def unseal(self, *, reference: str) -> str:
        return self.store[reference]

    async def delete(self, *, reference: str) -> None:
        self.store.pop(reference, None)
