from typing import Protocol


class AIImagePort(Protocol):
    """Provider-neutral port for hosted image generation. Concrete adapter:
    Replicate (see adapters/ai_image/replicate.py and
    28_OSS_TECHNOLOGY_STACK.md). Returns raw image bytes — the caller
    stores them via ObjectStoragePort, keeping the two ports orthogonal."""

    async def generate_image(self, *, prompt: str, model: str, params: dict) -> bytes: ...
