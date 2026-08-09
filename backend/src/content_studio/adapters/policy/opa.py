import httpx

from content_studio.config import Settings


class OPAPolicyAdapter:
    """Open Policy Agent REST API client — POST /v1/data/{path} with
    {"input": ...}, per OPA's standard evaluation API."""

    def __init__(self, settings: Settings) -> None:
        self._base_url = settings.opa_url.rstrip("/")

    async def evaluate(self, *, policy_path: str, input_data: dict) -> dict:
        path = policy_path.replace(".", "/")
        async with httpx.AsyncClient(timeout=10) as client:
            response = await client.post(f"{self._base_url}/v1/data/{path}", json={"input": input_data})
            response.raise_for_status()
            body = response.json()
        return body.get("result", {})
