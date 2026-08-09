import base64

# A real, minimal 1x1 transparent PNG so anything that decodes the bytes as
# an image still works in dev mode without a Replicate token configured.
_TINY_PNG_B64 = (
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNkYPhfDwAChwGA60e6kgAAAABJRU5ErkJggg=="
)


class StubAIImageAdapter:
    """Runtime fallback used when no replicate_api_token is configured —
    see StubAITextAdapter's docstring for why this is separate from the
    tests/fakes equivalent."""

    async def generate_image(self, *, prompt: str, model: str, params: dict) -> bytes:
        return base64.b64decode(_TINY_PNG_B64)
