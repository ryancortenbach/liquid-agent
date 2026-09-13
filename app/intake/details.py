from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field
from decimal import Decimal
from typing import Any

from app.models import ConditionGrade
from app.pricing.schedule import parse_horizon

ALL_PLATFORMS = ("ebay", "facebook", "offerup")
PLATFORM_ALIASES = {
    "ebay": "ebay",
    "facebook": "facebook",
    "fb": "facebook",
    "marketplace": "facebook",
    "offerup": "offerup",
    "offer up": "offerup",
    "craigslist": "craigslist",
}
ISSUE_WORDS = (
    "scratch", "scuff", "dent", "crack", "chip", "worn", "wear", "stain", "battery", "issue",
    "problem", "broken", "doesn't", "does not", "missing", "loose", "sticky", "fade", "tear",
)
INCLUDED_WORDS = ("box", "charger", "cable", "case", "manual", "receipt", "stand", "strap", "bag")


@dataclass(slots=True)
class IntakeDetails:
    condition: str | None = None  # A, B, C
    included: list[str] = field(default_factory=list)
    issues: list[str] = field(default_factory=list)
    horizon: str | None = None
    floor_cents: int | None = None  # 0 means "you decide"
    shipping: str | None = None  # ship, local, both
    zip_code: str | None = None
    platforms: list[str] | None = None
    answered_sets: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> IntakeDetails:
        if not data:
            return cls()
        known = {name for name in cls.__dataclass_fields__}  # type: ignore[attr-defined]
        return cls(**{key: value for key, value in data.items() if key in known})

    @property
    def condition_grade(self) -> ConditionGrade:
        return ConditionGrade(self.condition or "B")


def parse_condition(text: str, *, allow_digits: bool = False) -> tuple[str | None, list[str]]:
    """Grade from words anywhere; a bare 1-4 only counts as an answer to the condition question."""
    lowered = text.lower()
    issues: list[str] = []
    digit = re.match(r"\s*([1-4])\b", lowered) if allow_digits else None
    if re.search(r"\b(broken|for parts|doesn'?t (?:turn on|work))\b", lowered) or (
        digit and digit.group(1) == "4"
    ):
        issues.append("for parts or repair")
        return "C", issues
    if re.search(r"\b(like new|mint|excellent|flawless)\b", lowered) or (
        digit and digit.group(1) == "1"
    ):
        return "A", issues
    if re.search(r"\b(fair|visible|heavy|rough)\b", lowered) or (digit and digit.group(1) == "3"):
        return "C", issues
    if re.search(r"\b(good|light wear|lightly used|minor)\b", lowered) or (
        digit and digit.group(1) == "2"
    ):
        return "B", issues
    return None, issues


def parse_floor(text: str) -> int | None:
    lowered = text.lower()
    if re.search(r"\b(you decide|you pick|whatever|up to you|no floor)\b", lowered):
        return 0
    patterns = (
        r"(?:floor|minimum|min|lowest|not under|not below|at least|no less than|don'?t go under)"
        r"\s*(?:is\s*|of\s*)?\$?\s*([0-9]{2,6}(?:\.[0-9]{1,2})?)",
        r"\$\s*([0-9]{2,6}(?:\.[0-9]{1,2})?)",
    )
    for pattern in patterns:
        match = re.search(pattern, lowered)
        if match:
            return int(Decimal(match.group(1)) * 100)
    return None


def parse_shipping(text: str) -> tuple[str | None, str | None]:
    lowered = text.lower()
    zip_match = re.search(r"\b(\d{5})\b", lowered)
    zip_code = zip_match.group(1) if zip_match else None
    if re.search(r"\bboth\b", lowered):
        return "both", zip_code
    ship = bool(re.search(r"\b(ship|mail|post it)\b", lowered))
    local = bool(re.search(r"\b(local|pickup|pick up|meet)\b", lowered))
    if ship and local:
        return "both", zip_code
    if ship:
        return "ship", zip_code
    if local:
        return "local", zip_code
    return None, zip_code


def parse_platforms(text: str) -> list[str] | None:
    lowered = text.lower()
    if re.search(r"\b(all|everywhere|all of them)\b", lowered):
        return list(ALL_PLATFORMS)
    found = [
        platform
        for alias, platform in PLATFORM_ALIASES.items()
        if re.search(rf"\b{re.escape(alias)}\b", lowered)
    ]
    deduped = list(dict.fromkeys(found))
    return deduped or None


def parse_included_and_issues(text: str) -> tuple[list[str], list[str]]:
    lowered = text.lower()
    if re.search(r"\b(just the item|nothing else|no extras|item only)\b", lowered):
        return [], []
    fragments = [
        fragment.strip(" .")
        for fragment in re.split(r"[,;]|\band\b|\bbut\b|\bplus\b", lowered)
        if fragment.strip(" .")
    ]
    included: list[str] = []
    issues: list[str] = []
    for fragment in fragments:
        if any(word in fragment for word in ISSUE_WORDS):
            issues.append(fragment)
        elif any(word in fragment for word in INCLUDED_WORDS) or fragment.startswith(
            ("with ", "includes", "comes with", "has the")
        ):
            included.append(re.sub(r"^(with|includes|comes with|has the)\s+", "", fragment))
    return included, issues


def merge_details(existing: IntakeDetails, text: str, *, answered_set: str) -> IntakeDetails:
    details = IntakeDetails.from_dict(existing.as_dict())
    condition, condition_issues = parse_condition(text, allow_digits=answered_set == "condition")
    if condition:
        details.condition = condition
    included, issues = parse_included_and_issues(text)
    details.included = list(dict.fromkeys([*details.included, *included]))
    details.issues = list(dict.fromkeys([*details.issues, *issues, *condition_issues]))
    horizon = parse_horizon(text)
    if horizon:
        details.horizon = horizon
    floor = parse_floor(text)
    if floor is not None:
        details.floor_cents = floor
    shipping, zip_code = parse_shipping(text)
    if shipping:
        details.shipping = shipping
    if zip_code:
        details.zip_code = zip_code
    platforms = parse_platforms(text)
    if platforms:
        details.platforms = platforms
    if answered_set not in details.answered_sets:
        details.answered_sets.append(answered_set)
    return details


def apply_defaults(details: IntakeDetails) -> IntakeDetails:
    details.condition = details.condition or "B"
    details.horizon = details.horizon or "week"
    details.floor_cents = 0 if details.floor_cents is None else details.floor_cents
    details.shipping = details.shipping or "both"
    details.platforms = details.platforms or list(ALL_PLATFORMS)
    return details


# Only what a truthful, well-priced listing needs. Floor, shipping, and platforms default
# (you decide / both / everywhere) and can be changed in any reply, e.g. "not under 200".
QUESTION_SETS: dict[str, str] = {
    "condition": (
        "condition? 1 like new · 2 good · 3 fair · 4 broken\n"
        "anything included or wrong with it?"
    ),
    "plan": "how fast do you want it gone? 1 day · 3 days · week · month",
}


def next_question_set(details: IntakeDetails) -> str | None:
    for name in ("condition", "plan"):
        if name not in details.answered_sets:
            return name
    return None
