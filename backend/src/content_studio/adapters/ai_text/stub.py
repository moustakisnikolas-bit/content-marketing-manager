class StubAITextAdapter:
    """Runtime fallback used when no ai_text_api_key is configured, so the
    app runs out of the box without requiring paid provider keys. Distinct
    from tests/fakes/ai_text.py's FakeAIText: this ships with the
    application (src/) and is a deliberate dev-mode behavior, not a test
    double injectable with failure modes."""

    async def generate_text(self, *, prompt: str, model: str, params: dict) -> str:
        return (
            f"[stub output - configure CS_AI_TEXT_API_KEY for real generation]\n"
            f"Draft copy for: {prompt[:200]}"
        )
