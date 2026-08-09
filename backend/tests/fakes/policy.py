class FakePolicy:
    """In-memory PolicyPort implementation with a configurable canned
    result, for testing guardrail-consuming code without a live OPA."""

    def __init__(self, *, result: dict | None = None) -> None:
        self.result = result if result is not None else {"allow": True, "deny_reasons": []}
        self.calls: list[dict] = []

    async def evaluate(self, *, policy_path: str, input_data: dict) -> dict:
        self.calls.append({"policy_path": policy_path, "input": input_data})
        return self.result
