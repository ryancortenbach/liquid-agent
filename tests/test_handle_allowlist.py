from __future__ import annotations

from app.channels.seller_router import (
    WILDCARD_ALLOWLIST,
    canonical_handle,
    parse_handle_allowlist,
)

FRIEND = "+17377773040"
STRANGER = "+16056666296"


def test_blank_settings_allow_nobody() -> None:
    """A missing or empty SELLER_HANDLE must never be read as "allow everyone"."""
    for value in (None, "", "   ", ",", " , , "):
        assert parse_handle_allowlist(value) == frozenset(), value


def test_single_handle_allows_only_that_handle() -> None:
    allowlist = parse_handle_allowlist(FRIEND)
    assert allowlist == frozenset({FRIEND})
    assert STRANGER not in allowlist


def test_handles_are_canonicalized_before_comparison() -> None:
    """Formatting differences in the env file must not silently lock the friend out."""
    for written in ("+1 (737) 777-3040", " +1-737-777-3040 ", "+1.737.777.3040"):
        assert parse_handle_allowlist(written) == frozenset({FRIEND}), written


def test_comma_separated_handles_are_all_allowed() -> None:
    allowlist = parse_handle_allowlist(f"{FRIEND}, {STRANGER}")
    assert allowlist == frozenset({FRIEND, STRANGER})


def test_email_handles_are_lowercased_not_stripped_of_punctuation() -> None:
    assert parse_handle_allowlist("RyanCortenbach77@GMAIL.com") == frozenset(
        {"ryancortenbach77@gmail.com"}
    )


def test_only_a_bare_star_opens_liquid_to_everyone() -> None:
    assert parse_handle_allowlist("*") == WILDCARD_ALLOWLIST
    assert parse_handle_allowlist(f"{FRIEND},*") == WILDCARD_ALLOWLIST
    # A handle that merely contains a star is not a wildcard.
    assert parse_handle_allowlist("+1737777304*") != WILDCARD_ALLOWLIST


def test_canonical_handle_matches_what_the_allowlist_stores() -> None:
    assert canonical_handle("+1 (737) 777-3040") == FRIEND
