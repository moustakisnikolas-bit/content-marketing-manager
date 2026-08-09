class FakeAIText:
    """In-memory AITextPort implementation. Deterministic output so tests
    can assert on it; supports injecting a fixed response or raising, to
    exercise the quality-gate and failure paths without a real provider."""

    def __init__(self, *, fixed_response: str | None = None, should_fail: bool = False) -> None:
        self.fixed_response = fixed_response
        self.should_fail = should_fail
        self.calls: list[dict] = []

    async def generate_text(self, *, prompt: str, model: str, params: dict) -> str:
        self.calls.append({"prompt": prompt, "model": model, "params": params})
        if self.should_fail:
            raise RuntimeError("simulated provider failure")
        if self.fixed_response is not None:
            return self.fixed_response
        return f"Generated copy for: {prompt[:80]}"
