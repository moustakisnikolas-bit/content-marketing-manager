import uuid

import httpx

from content_studio.config import Settings


class OpenBaoSecretsAdapter:
    """OpenBao KV v2 HTTP API client (API-compatible with HashiCorp Vault).
    Dev mode uses a static root token from docker-compose; production
    would use a proper auth method (AppRole, Kubernetes, etc.) instead of
    a long-lived static token — that's an infra hardening step, not an
    adapter-shape change."""

    def __init__(self, settings: Settings) -> None:
        self._base_url = settings.openbao_url.rstrip("/")
        self._token = settings.openbao_token
        self._mount = settings.openbao_secret_mount

    def _headers(self) -> dict:
        return {"X-Vault-Token": self._token}

    async def seal(self, *, value: str) -> str:
        reference = f"platform-tokens/{uuid.uuid4()}"
        async with httpx.AsyncClient(timeout=10) as client:
            response = await client.post(
                f"{self._base_url}/v1/{self._mount}/data/{reference}",
                headers=self._headers(),
                json={"data": {"value": value}},
            )
            response.raise_for_status()
        return reference

    async def unseal(self, *, reference: str) -> str:
        async with httpx.AsyncClient(timeout=10) as client:
            response = await client.get(
                f"{self._base_url}/v1/{self._mount}/data/{reference}", headers=self._headers()
            )
            response.raise_for_status()
            body = response.json()
        return body["data"]["data"]["value"]

    async def delete(self, *, reference: str) -> None:
        async with httpx.AsyncClient(timeout=10) as client:
            response = await client.delete(
                f"{self._base_url}/v1/{self._mount}/metadata/{reference}", headers=self._headers()
            )
            if response.status_code not in (200, 204, 404):
                response.raise_for_status()
