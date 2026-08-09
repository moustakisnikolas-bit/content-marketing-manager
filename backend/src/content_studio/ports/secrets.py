from typing import Protocol


class SecretsPort(Protocol):
    """Provider-neutral port for secret storage. Concrete adapter: OpenBao
    (see adapters/secrets/openbao.py), per the spec's hard rule that no
    OAuth token or provider credential is ever stored in plaintext in
    PostgreSQL — business tables hold only the opaque reference this port
    returns."""

    async def seal(self, *, value: str) -> str:
        """Stores value, returns an opaque reference to store in Postgres
        instead of the value itself."""
        ...

    async def unseal(self, *, reference: str) -> str:
        """Resolves a reference back to its plaintext value."""
        ...

    async def delete(self, *, reference: str) -> None: ...
