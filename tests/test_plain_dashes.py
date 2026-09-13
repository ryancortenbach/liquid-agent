from __future__ import annotations

from app.channels.imessage_bluebubbles import plain_dashes


def test_em_dash_becomes_a_comma() -> None:
    assert plain_dashes("Hi — what can I help with?") == "Hi, what can I help with?"


def test_en_dash_is_stripped_too() -> None:
    assert plain_dashes("Listed – waiting on offers") == "Listed, waiting on offers"


def test_dash_with_no_surrounding_spaces() -> None:
    assert plain_dashes("Done—finally.") == "Done, finally."


def test_numeric_range_keeps_a_plain_hyphen() -> None:
    assert plain_dashes("sell by 5—6pm") == "sell by 5-6pm"


def test_several_dashes_in_one_message() -> None:
    assert plain_dashes("a — b — c") == "a, b, c"


def test_a_dash_before_punctuation_does_not_leave_a_stray_comma() -> None:
    assert plain_dashes("I can do that —.") == "I can do that."


def test_text_without_dashes_is_unchanged() -> None:
    message = "Nothing's in progress right now. Send me a photo whenever you're ready."
    assert plain_dashes(message) == message


def test_no_outgoing_message_can_contain_an_em_dash() -> None:
    for raw in ("— lead", "trail —", "a—b—c—d", "5—6", "x — y."):
        assert "—" not in plain_dashes(raw)
        assert "–" not in plain_dashes(raw)
