from __future__ import annotations

from app.intake.details import (
    IntakeDetails,
    apply_defaults,
    merge_details,
    next_question_set,
    parse_floor,
    parse_platforms,
    parse_shipping,
)


def test_condition_set_parses_grade_included_and_issues() -> None:
    details = merge_details(
        IntakeDetails(),
        "2, comes with the box and charger, small scratch on the back",
        answered_set="condition",
    )
    assert details.condition == "B"
    assert details.included == ["the box", "charger"]
    assert details.issues == ["small scratch on the back"]
    assert next_question_set(details) == "plan"


def test_plan_set_parses_horizon_floor_shipping_platforms() -> None:
    details = merge_details(
        IntakeDetails(answered_sets=["condition"]),
        "3 days, not under $220, both, 94110, all",
        answered_set="plan",
    )
    assert details.horizon == "3 days"
    assert details.floor_cents == 22_000
    assert details.shipping == "both" and details.zip_code == "94110"
    assert details.platforms == ["ebay", "facebook", "offerup"]
    assert next_question_set(details) is None


def test_free_text_fills_several_fields_at_once() -> None:
    details = merge_details(
        IntakeDetails(),
        "good condition, just the item, need it gone by tomorrow, you decide the price, "
        "local only, ebay and facebook",
        answered_set="condition",
    )
    assert details.condition == "B"
    assert details.included == [] and details.issues == []
    assert details.horizon == "1 day"
    assert details.floor_cents == 0
    assert details.shipping == "local"
    assert details.platforms == ["ebay", "facebook"]


def test_defaults_fill_missing_answers() -> None:
    details = apply_defaults(IntakeDetails(answered_sets=["condition", "plan"]))
    assert (details.condition, details.horizon, details.floor_cents, details.shipping) == (
        "B", "week", 0, "both"
    )
    assert details.platforms == ["ebay", "facebook", "offerup"]
    assert details.condition_grade.value == "B"


def test_parsers_edge_cases() -> None:
    assert parse_floor("lowest 250") == 25_000
    assert parse_floor("whatever you think") == 0
    assert parse_floor("no number here") is None
    assert parse_shipping("ship it") == ("ship", None)
    assert parse_platforms("fb and offer up") == ["facebook", "offerup"]
    assert parse_platforms("somewhere") is None
    assert IntakeDetails.from_dict({"condition": "A", "unknown": 1}).condition == "A"
