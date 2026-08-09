from decimal import Decimal

from content_studio.modules.marketing.proposal_generator import generate_proposal_draft


def test_generates_one_item_per_platform() -> None:
    draft = generate_proposal_draft(
        goal_label="Brand awareness",
        goal_slug="brand_awareness",
        what_to_promote="our new eco-friendly water bottle",
        target_platforms=["facebook", "instagram"],
        per_item_estimated_cost=Decimal("0.50"),
    )

    assert len(draft.plan_items) == 2
    assert {i.platform for i in draft.plan_items} == {"facebook", "instagram"}
    assert draft.estimated_cost == Decimal("1.00")


def test_generates_at_least_one_item_with_no_platforms_selected() -> None:
    draft = generate_proposal_draft(
        goal_label="Brand awareness",
        goal_slug="brand_awareness",
        what_to_promote="our new product",
        target_platforms=[],
        per_item_estimated_cost=Decimal("0.50"),
    )

    assert len(draft.plan_items) == 1
    assert draft.plan_items[0].platform is None
    assert draft.estimated_cost == Decimal("0.50")


def test_explanation_does_not_claim_performance_evidence() -> None:
    draft = generate_proposal_draft(
        goal_label="More sales",
        goal_slug="more_sales",
        what_to_promote="our spring collection",
        target_platforms=["facebook"],
        per_item_estimated_cost=Decimal("0.50"),
    )

    # Must not fabricate performance claims — no data exists yet at
    # proposal time (09_RECOMMENDATION_ENGINE.md's anti-overclaiming rule).
    assert "guarantee" not in draft.explanation.lower()
    assert "plan, not a promise" in draft.explanation.lower()


def test_assumptions_are_explicit() -> None:
    draft = generate_proposal_draft(
        goal_label="More sales",
        goal_slug="more_sales",
        what_to_promote="our spring collection",
        target_platforms=["facebook", "tiktok"],
        per_item_estimated_cost=Decimal("1.25"),
    )

    assert len(draft.assumptions) >= 2
    assert any("2 post" in a for a in draft.assumptions)
