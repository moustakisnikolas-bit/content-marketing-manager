from dataclasses import dataclass, field

from content_studio.modules.identity.models import BrandRule


@dataclass(frozen=True)
class QualityGateResult:
    passed: bool
    violations: list[str] = field(default_factory=list)


def check_text_against_brand_rules(text: str, rules: list[BrandRule]) -> QualityGateResult:
    """Deterministic, explainable keyword check — matches the spec's
    'start with deterministic scoring, not predictive models' rule for
    early-stage automated decisions (same philosophy as the Phase 5
    recommendation engine). A blocking rule whose description phrase
    appears in the generated text fails the gate; non-blocking rules are
    recorded but don't fail it."""
    lowered = text.lower()
    violations: list[str] = []

    for rule in rules:
        phrase = rule.description.strip().lower()
        if not phrase:
            continue
        if phrase in lowered:
            marker = "" if rule.is_blocking else " (advisory)"
            violations.append(f"{rule.rule_type}: '{rule.description}'{marker}")

    blocking_violation_found = any(
        rule.description.strip().lower() in lowered for rule in rules if rule.is_blocking
    )
    return QualityGateResult(passed=not blocking_violation_found, violations=violations)
