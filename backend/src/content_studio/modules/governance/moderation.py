import re
from dataclasses import dataclass

# Deterministic pattern matching, no ML/LLM — same philosophy as the
# analytics recommendation engine: a control that can be explained and
# tested exactly, not a black box. This is the concrete mechanism behind
# 15_MCP_AGENTS_AND_SECURITY.md's 'untrusted content never treated as
# instruction' rule: any text an agent tool call pulls from an external,
# untrusted source (a synced product description, a webhook payload field,
# free-form brief text) is scanned before it's allowed to flow into a
# tool call or an AI-facing prompt. A match blocks the call outright — it
# never tries to 'sanitize' and continue, since a cleverly-encoded
# injection surviving a naive strip is worse than an honest refusal.
_INJECTION_PATTERNS: list[re.Pattern[str]] = [
    re.compile(r"ignore (all |any )?(the )?(previous|prior|above)\s+instructions?", re.IGNORECASE),
    re.compile(r"disregard (all |any )?(the )?(previous|prior|above)", re.IGNORECASE),
    re.compile(r"\byou are now\b", re.IGNORECASE),
    re.compile(r"\bnew instructions?\s*:", re.IGNORECASE),
    re.compile(r"^\s*system\s*:", re.IGNORECASE | re.MULTILINE),
    re.compile(r"reveal (your|the) (system )?prompt", re.IGNORECASE),
    re.compile(r"</?\s*(system|instructions?)\s*>", re.IGNORECASE),
    re.compile(r"\bact as\b.{0,30}\b(admin|administrator|root|developer mode)\b", re.IGNORECASE),
]

_EXCERPT_MAX_LENGTH = 500


@dataclass(frozen=True)
class ModerationResult:
    allowed: bool
    detected_patterns: list[str]
    excerpt: str


def scan_untrusted_text(text: str) -> ModerationResult:
    """Never raises, never modifies `text` — only reports. Callers decide
    what to do with a blocked result (GovernanceService refuses the tool
    call and records a ModerationDecision either way)."""
    detected = [pattern.pattern for pattern in _INJECTION_PATTERNS if pattern.search(text)]
    return ModerationResult(
        allowed=len(detected) == 0,
        detected_patterns=detected,
        excerpt=text[:_EXCERPT_MAX_LENGTH],
    )
