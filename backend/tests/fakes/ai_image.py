import base64

# A real, minimal 1x1 transparent PNG — valid bytes, not just a placeholder
# string, in case anything downstream ever tries to decode it as an image.
_TINY_PNG_B64 = (
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNkYPhfDwAChwGA60e6kgAAAABJRU5ErkJggg=="
)


class FakeAIImage:
    """In-memory AIImagePort implementation."""

    def __init__(self, *, should_fail: bool = False) -> None:
        self.should_fail = should_fail
        self.calls: list[dict] = []

    async def generate_image(
        self, *, prompt: str, model: str, params: dict, reference_image_url: str | None = None
    ) -> bytes:
        self.calls.append(
            {"prompt": prompt, "model": model, "params": params, "reference_image_url": reference_image_url}
        )
        if self.should_fail:
            raise RuntimeError("simulated provider failure")
        return base64.b64decode(_TINY_PNG_B64)
