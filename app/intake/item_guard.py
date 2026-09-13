from __future__ import annotations

import re

SELL_INTENT_PATTERN = re.compile(
    r"\b(?:(?:i\s+)?(?:also\s+)?(?:want|need|would\s+like)\s+to\s+)?"
    r"(?:sell|list|post)\s+(?:(?:my|the|an?|some)\s+)?",
    flags=re.IGNORECASE,
)
DETAIL_STOP_PATTERN = re.compile(
    r"\s+(?:by|before|deadline|minimum|min|floor|do not|don't|dont|not under|not below)\b",
    flags=re.IGNORECASE,
)
TRAILING_CONNECTOR_PATTERN = re.compile(
    r"[\s,;:]*(?:(?:and\s+)?then|and|also|next)[\s,;:]*$",
    flags=re.IGNORECASE,
)
SHARED_INTENT_SEPARATOR_PATTERN = re.compile(
    r"\s*(?:,|;)?\s+(?:(?:and\s+)?then|and)\s+(?:(?:my|the|an?|some)\s+)",
    flags=re.IGNORECASE,
)
ITEM_PRONOUN_PATTERN = re.compile(
    r"^(?:it|them|this|that|these|those)(?:\s+items?)?(?:\s|$)",
    flags=re.IGNORECASE,
)


def _clean_candidate(candidate: str) -> str:
    while TRAILING_CONNECTOR_PATTERN.search(candidate):
        candidate = TRAILING_CONNECTOR_PATTERN.sub("", candidate)
    candidate = DETAIL_STOP_PATTERN.split(candidate, maxsplit=1)[0]
    return candidate.strip(" \t\n.,;:!?-")


def extract_separate_item_requests(text: str) -> list[str]:
    """Return item names only when the seller repeats a clear sell or list intent."""
    matches = list(SELL_INTENT_PATTERN.finditer(text))
    candidates: list[str]
    if len(matches) >= 2:
        candidates = []
        for index, match in enumerate(matches):
            end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
            candidates.append(text[match.end() : end])
    elif len(matches) == 1:
        candidates = SHARED_INTENT_SEPARATOR_PATTERN.split(text[matches[0].end() :])
        if len(candidates) < 2:
            return []
    else:
        return []

    items: list[str] = []
    seen: set[str] = set()
    for raw_candidate in candidates:
        candidate = _clean_candidate(raw_candidate)
        if not candidate or len(candidate) > 120 or ITEM_PRONOUN_PATTERN.match(candidate):
            continue
        key = candidate.casefold()
        if key not in seen:
            items.append(candidate)
            seen.add(key)

    return items if len(items) >= 2 else []


def separate_items_reply(items: list[str]) -> str:
    summary = "\n".join(f"{index}. {item}" for index, item in enumerate(items, start=1))
    return (
        f"I caught {len(items)} separate items and won't combine them:\n{summary}\n"
        "Send one photo per item, or attach everything with a BATCH label."
    )
