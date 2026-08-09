from typing import Protocol


class AIAudioPort(Protocol):
    """Provider-neutral port for hosted audio generation (voiceover,
    music). Concrete adapter: Replicate (see adapters/ai_audio/replicate.py),
    same hosted-inference-by-default decision as AIImagePort. Returns raw
    audio bytes — the caller stores them via ObjectStoragePort, keeping the
    two ports orthogonal."""

    async def generate_audio(self, *, prompt: str, model: str, params: dict) -> bytes: ...
