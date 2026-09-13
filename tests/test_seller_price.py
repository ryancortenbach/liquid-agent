from __future__ import annotations

from app.intake.details import IntakeDetails, merge_details, parse_asking
from app.intake.router import has_change_request


def test_for_dollar_amount_is_an_asking_price() -> None:
    assert parse_asking("Sell it on EBAY only for $300") == 30_000
    assert parse_asking("list at 250") == 25_000
    assert parse_asking("price it at $199.99") == 19_999
    assert parse_asking("asking 120") == 12_000


def test_floor_phrases_are_not_asking_prices() -> None:
    assert parse_asking("floor 250") is None
    assert parse_asking("not under $200") is None
    assert parse_asking("at least 150") is None


def test_plain_numbers_and_deadlines_are_not_prices() -> None:
    assert parse_asking("3 days") is None
    assert parse_asking("1 day") is None
    assert parse_asking("2") is None


def test_change_message_sets_price_and_channel_without_touching_floor() -> None:
    details = merge_details(
        IntakeDetails(floor_cents=15_000), "Sell it on EBAY only for $300", answered_set="change"
    )
    assert details.asking_cents == 30_000
    assert details.platforms == ["ebay"]
    assert details.floor_cents == 15_000


def test_bare_dollar_amount_still_reads_as_a_floor() -> None:
    details = merge_details(IntakeDetails(), "$300", answered_set="change")
    assert details.floor_cents == 30_000
    assert details.asking_cents is None


def test_change_requests_are_not_a_bare_go() -> None:
    for text in (
        "Sell it on EBAY only for $300",
        "go, but ebay only",
        "post it for 250",
        "do it, 1 day",
        "list it, floor 200",
    ):
        assert has_change_request(text), text
    for text in ("go", "yes", "post it", "do it", "go ahead", "ship it"):
        assert not has_change_request(text), text
