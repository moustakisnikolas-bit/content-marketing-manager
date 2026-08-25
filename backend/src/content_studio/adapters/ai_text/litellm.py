import httpx

from content_studio.config import Settings


class LiteLLMTextAdapter:
    """Calls an OpenAI-compatible chat-completions endpoint. Points at
    OpenRouter directly by default (see Settings.ai_text_base_url); pointing
    this at a self-hosted LiteLLM Proxy instead — the OSS stack's actual
    recommendation, see 28_OSS_TECHNOLOGY_STACK.md — is a base_url/api_key
    config change only, since LiteLLM Proxy re-exposes the same
    OpenAI-compatible surface. Deploying that proxy as its own
    docker-compose service is a follow-up, not required for this adapter's
    correctness."""

    def __init__(self, settings: Settings) -> None:
        self._base_url = settings.ai_text_base_url.rstrip("/")
        self._api_key = settings.ai_text_api_key
        self._output_language = settings.ai_text_output_language

    async def generate_text(self, *, prompt: str, model: str, params: dict) -> str:
        headers = {"Authorization": f"Bearer {self._api_key}", "Content-Type": "application/json"}
        messages = []
        if self._output_language:
            # Without this, output language just follows whatever language
            # the brief happens to be written in — most briefs here are
            # typed in English, which silently produced English content
            # regardless of the workspace's actual target audience.
            messages.append(
                {
                    "role": "system",
                    "content": f"Always respond in {self._output_language}, regardless of what language the "
                    f"brief below is written in.",
                }
            )
        messages.append({"role": "user", "content": prompt})
        payload = {
            "model": model,
            "messages": messages,
            **params,
        }
        async with httpx.AsyncClient(timeout=httpx.Timeout(connect=10, read=60, write=10, pool=10)) as client:
            response = await client.post(f"{self._base_url}/chat/completions", headers=headers, json=payload)
            response.raise_for_status()
            body = response.json()
        return body["choices"][0]["message"]["content"]
