from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import Any

from app.intake.details import IntakeDetails
from app.models import Item

log = logging.getLogger(__name__)

CONDITION_LABEL = {"A": "like new", "B": "good, light wear", "C": "fair, visible wear"}
EBAY_CONDITION = {"A": "USED_EXCELLENT", "B": "USED_VERY_GOOD", "C": "USED_ACCEPTABLE"}
ASPECT_KEYS = ("Brand", "Model", "Storage Capacity", "Storage", "Color", "Connectivity", "Type")


@dataclass(frozen=True, slots=True)
class ListingDraft:
    title: str
    description: str
    condition: str
    aspects: dict[str, list[str]]
    facts: dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return {
            "title": self.title,
            "description": self.description,
            "condition": self.condition,
            "aspects": self.aspects,
            "facts": self.facts,
        }


def _clean(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def clean_item_title(title: str) -> str:
    """Drop caption residue such as a trailing ', sell' left by the intake parser."""
    cleaned = re.sub(r"[,;:\-\s]*(?:please\s+)?(?:sell|list)(?:\s+(?:it|this|these))?\s*$", "",
                     _clean(title), flags=re.IGNORECASE)
    return cleaned.strip(" ,;:-") or _clean(title)


def build_title(item: Item, specifics: dict[str, Any]) -> str:
    parts = [item.brand, item.model, clean_item_title(item.title)]
    seen: list[str] = []
    for part in parts:
        for token in _clean(part or "").split(" "):
            if token and token.lower() not in {t.lower() for t in seen}:
                seen.append(token)
    for key in ("Storage Capacity", "Storage", "Color"):
        value = specifics.get(key)
        if isinstance(value, str) and value.lower() not in " ".join(seen).lower():
            seen.append(value)
    title = " ".join(seen)
    grade = CONDITION_LABEL.get(item.condition.value, "used")
    suffix = f" - {grade}"
    return (title[: 80 - len(suffix)] + suffix) if len(title) + len(suffix) <= 80 else title[:80]


def build_description(item: Item, details: IntakeDetails) -> str:
    grade = CONDITION_LABEL.get(details.condition or item.condition.value, "used")
    lines = [f"{clean_item_title(item.title)}.", f"Condition: {grade}."]
    if details.issues:
        lines.append(
            "Wear and issues, as described by the seller: " + "; ".join(details.issues) + "."
        )
    else:
        lines.append("No defects reported by the seller beyond normal use.")
    if details.included:
        lines.append("Included: " + ", ".join(details.included) + ".")
    else:
        lines.append("Item only, no accessories included.")
    shipping = details.shipping or "both"
    near = f" near {details.zip_code}" if details.zip_code else ""
    if shipping == "local":
        lines.append(f"Local pickup only{near}.")
    elif shipping == "ship":
        lines.append("Ships within one business day of payment.")
    else:
        lines.append(f"Ships within one business day, or local pickup{near}.")
    lines.append(
        "Photos show the actual item. The untouched original photo is included in the set."
    )
    return "\n".join(lines)


def build_aspects(item: Item, specifics: dict[str, Any]) -> dict[str, list[str]]:
    aspects: dict[str, list[str]] = {}
    if item.brand:
        aspects["Brand"] = [item.brand]
    if item.model:
        aspects["Model"] = [item.model]
    for key in ASPECT_KEYS:
        value = specifics.get(key)
        if isinstance(value, str) and value and key not in aspects:
            aspects[key] = [value]
    if not aspects:
        aspects["Type"] = [_clean(item.title)[:65] or "Item"]
    return aspects


def build_listing_draft(
    item: Item, details: IntakeDetails, specifics: dict[str, Any] | None = None
) -> ListingDraft:
    specifics = specifics or {}
    condition_code = details.condition or item.condition.value
    return ListingDraft(
        title=build_title(item, specifics),
        description=build_description(item, details),
        condition=EBAY_CONDITION.get(condition_code, "USED_GOOD"),
        aspects=build_aspects(item, specifics),
        facts={
            "condition": condition_code,
            "included": list(details.included),
            "issues": list(details.issues),
            "shipping": details.shipping,
        },
    )


def grounded(polished: str, draft: ListingDraft) -> bool:
    """A polished description may only rephrase: every disclosed issue and inclusion survives."""
    lowered = polished.lower()
    for phrase in [*draft.facts.get("issues", []), *draft.facts.get("included", [])]:
        key = re.findall(r"[a-z0-9]+", phrase.lower())
        if key and not all(token in lowered for token in key[:2]):
            return False
    forbidden = ("brand new", "sealed", "mint") if draft.facts.get("condition") != "A" else ()
    return not any(word in lowered for word in forbidden)


def polish_with_claude(draft: ListingDraft, *, api_key: str, model: str) -> ListingDraft:
    """Optional: tighter marketplace copy from Claude, kept only if it stays grounded."""
    try:
        import anthropic
        from pydantic import BaseModel

        class Copy(BaseModel):
            title: str
            description: str

        client = anthropic.Anthropic(api_key=api_key, timeout=20.0, max_retries=1)
        response = client.messages.parse(
            model=model,
            max_tokens=1200,
            system=(
                "You write truthful used-item marketplace listings. Rewrite the given draft for "
                "clarity and buyer confidence. Do not add any fact, accessory, feature, or "
                "condition claim that is not in the draft. Keep every disclosed issue. "
                "Title at most 80 characters, no all caps, no emojis."
            ),
            messages=[
                {"role": "user", "content": draft.description + "\n\nTITLE: " + draft.title}
            ],
            output_format=Copy,
        )
        copy = response.parsed_output
        if copy is None or not grounded(copy.description, draft):
            return draft
        return ListingDraft(
            title=copy.title[:80],
            description=copy.description,
            condition=draft.condition,
            aspects=draft.aspects,
            facts=draft.facts,
        )
    except Exception as exc:  # the template is always an acceptable listing
        log.warning("claude polish skipped: %s", exc)
        return draft
