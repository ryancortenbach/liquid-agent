from __future__ import annotations

import csv
from dataclasses import dataclass
from pathlib import Path

from app.listing.draft import ListingDraft

FACEBOOK_CONDITION = {"USED_EXCELLENT": "Used - Like New", "USED_VERY_GOOD": "Used - Good",
                      "USED_ACCEPTABLE": "Used - Fair", "USED_GOOD": "Used - Good"}


@dataclass(frozen=True, slots=True)
class Handoff:
    channel: str
    copy_text: str
    file_path: str | None


def dollars(cents: int) -> str:
    return f"${cents / 100:,.0f}"


def facebook_copy(draft: ListingDraft, price_cents: int, zip_code: str | None) -> str:
    return "\n".join(
        [
            "facebook marketplace, paste into the create-listing form:",
            f"title: {draft.title}",
            f"price: {dollars(price_cents)}",
            f"condition: {FACEBOOK_CONDITION.get(draft.condition, 'Used - Good')}",
            f"location: {zip_code or 'your zip'}",
            "description:",
            draft.description,
        ]
    )


def offerup_copy(draft: ListingDraft, price_cents: int, zip_code: str | None) -> str:
    return "\n".join(
        [
            "offerup, paste into the post form:",
            f"title: {draft.title}",
            f"price: {dollars(price_cents)}",
            "condition: "
            + FACEBOOK_CONDITION.get(draft.condition, "Used - Good").removeprefix("Used - "),
            f"location: {zip_code or 'your zip'}",
            "description:",
            draft.description,
        ]
    )


def write_facebook_csv(
    directory: Path,
    draft: ListingDraft,
    price_cents: int,
    zip_code: str | None,
    image_urls: list[str],
) -> Path:
    """One-row CSV for browser form-filler extensions (AutoList-style columns)."""
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / "facebook_marketplace_listing.csv"
    with path.open("w", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(
            ["Title", "Price", "Condition", "Category", "Description", "Location", "Image URLs"]
        )
        writer.writerow(
            [
                draft.title,
                f"{price_cents / 100:.2f}",
                FACEBOOK_CONDITION.get(draft.condition, "Used - Good"),
                "Electronics",
                draft.description,
                zip_code or "",
                " | ".join(image_urls),
            ]
        )
    return path


def build_handoffs(
    *,
    handoff_root: Path,
    item_id: str,
    draft: ListingDraft,
    price_cents: int,
    zip_code: str | None,
    image_urls: list[str],
    platforms: list[str],
) -> list[Handoff]:
    handoffs: list[Handoff] = []
    directory = handoff_root / item_id
    if "facebook" in platforms:
        csv_path = write_facebook_csv(directory, draft, price_cents, zip_code, image_urls)
        text = facebook_copy(draft, price_cents, zip_code)
        (directory / "facebook.txt").write_text(text)
        handoffs.append(Handoff("facebook", text, str(csv_path)))
    if "offerup" in platforms:
        text = offerup_copy(draft, price_cents, zip_code)
        directory.mkdir(parents=True, exist_ok=True)
        path = directory / "offerup.txt"
        path.write_text(text)
        handoffs.append(Handoff("offerup", text, str(path)))
    if "craigslist" in platforms:
        text = facebook_copy(draft, price_cents, zip_code).replace(
            "facebook marketplace", "craigslist"
        )
        directory.mkdir(parents=True, exist_ok=True)
        path = directory / "craigslist.txt"
        path.write_text(text)
        handoffs.append(Handoff("craigslist", text, str(path)))
    return handoffs
