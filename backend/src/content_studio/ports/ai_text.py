from typing import Protocol


class AITextPort(Protocol):
    """Provider-neutral port for hosted text/vision generation. Concrete
    adapter: LiteLLM Proxy routing to OpenRouter (see
    adapters/ai_text/litellm.py and 28_OSS_TECHNOLOGY_STACK.md)."""

    async def generate_text(self, *, prompt: str, model: str, params: dict) -> str: ...
