from typing import Protocol


class PolicyPort(Protocol):
    """Provider-neutral port for policy decisions. Concrete adapter: Open
    Policy Agent (see adapters/policy/opa.py) — the mandated policy engine
    for every Auto-Pilot guardrail check, per
    08_AUTOPILOT_MARKETING_MODE.md's 'cannot bypass ... OPA policy' rule."""

    async def evaluate(self, *, policy_path: str, input_data: dict) -> dict:
        """policy_path is dot-separated, matching the Rego package (e.g.
        'content_studio.autopilot'). Returns the policy's full result
        object (e.g. {"allow": bool, "deny_reasons": [...]})."""
        ...
