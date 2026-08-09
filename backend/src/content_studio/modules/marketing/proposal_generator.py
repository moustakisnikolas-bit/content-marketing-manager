from dataclasses import dataclass
from decimal import Decimal


@dataclass(frozen=True)
class ProposedItem:
    title: str
    brief_text: str
    platform: str | None


@dataclass(frozen=True)
class ProposalDraft:
    objective: str
    assumptions: list[str]
    plan_summary: str
    plan_items: list[ProposedItem]
    estimated_cost: Decimal
    explanation: str


def generate_proposal_draft(
    *,
    goal_label: str,
    goal_slug: str,
    what_to_promote: str,
    target_platforms: list[str],
    per_item_estimated_cost: Decimal,
) -> ProposalDraft:
    """Deterministic, rule-based campaign planning — no LLM call, no
    invented evidence. Matches the spec's 'start with deterministic
    scoring, not predictive models' philosophy (09_RECOMMENDATION_ENGINE.md)
    applied to planning: one text post per selected platform (at least
    one, even with no platform selected yet), a fixed, transparent
    cadence rather than a black-box AI-generated plan. Real
    recommendation-driven cadence (best day/time/format) is Phase 5
    territory, layered on top of this once real performance history
    exists."""
    platforms: list[str | None] = [p for p in target_platforms] if target_platforms else [None]
    items: list[ProposedItem] = []
    for index, platform in enumerate(platforms, start=1):
        platform_label = platform.title() if platform else "your channels"
        items.append(
            ProposedItem(
                title=f"{goal_label} post {index} ({platform_label})",
                brief_text=f"Write a post about: {what_to_promote}. Goal: {goal_label}.",
                platform=platform,
            )
        )

    estimated_cost = per_item_estimated_cost * len(items)
    assumptions = [
        "Uses your workspace's default text content recipe.",
        "Assumes no revisions beyond the first draft.",
        f"Assumes {len(items)} post(s) across {len(target_platforms) or 0} connected platform(s).",
    ]
    plan_summary = (
        f"{len(items)} text post(s) to support '{goal_label}', one per selected platform, "
        f"each starting from the same brief: {what_to_promote}"
    )
    explanation = (
        f"Based on your goal to achieve {goal_label.lower()} and what you told us about "
        f"'{what_to_promote}', we're proposing {len(items)} post(s) as a starting plan. "
        "This is a plan, not a promise of results - we don't have performance history for "
        "this goal yet, so there's no outcome estimate attached. You can review and edit "
        "everything before anything is created."
    )

    return ProposalDraft(
        objective=f"{goal_label}: {what_to_promote}",
        assumptions=assumptions,
        plan_summary=plan_summary,
        plan_items=items,
        estimated_cost=estimated_cost,
        explanation=explanation,
    )
