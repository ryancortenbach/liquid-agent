from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Literal, Protocol

CompKind = Literal["sold", "active"]

FIXTURE_DIR = Path(__file__).parent / "fixtures"


@dataclass(frozen=True, slots=True)
class CompRecord:
    title: str
    price_cents: int
    kind: CompKind
    source: str
    url: str | None = None
    condition: str | None = None
    sold_at: str | None = None
    image_url: str | None = None
    specifics: dict[str, Any] = field(default_factory=dict)

    def to_source(self) -> dict[str, Any]:
        return {
            "title": self.title,
            "price_cents": self.price_cents,
            "kind": self.kind,
            "source": self.source,
            "url": self.url,
            "sold_at": self.sold_at,
            "condition": self.condition,
        }


class CompsSource(Protocol):
    name: str

    async def search(self, query: str, *, kind: CompKind, max_results: int) -> list[CompRecord]: ...


def _to_cents(value: Any) -> int | None:
    if value is None:
        return None
    if isinstance(value, int | float):
        return int(round(float(value) * 100)) if value > 0 else None
    text = str(value)
    match = re.search(r"([0-9]{1,6}(?:[.,][0-9]{1,2})?)", text.replace(",", ""))
    if not match:
        return None
    return int(round(float(match.group(1)) * 100))


def normalize_record(raw: dict[str, Any], *, kind: CompKind, source: str) -> CompRecord | None:
    """Tolerant mapping from any of the Apify eBay actors' output shapes."""
    title = raw.get("title") or raw.get("name")
    if not title:
        return None
    price_cents = None
    for key in ("priceValue", "soldPrice", "price", "totalPrice", "priceText", "currentPrice"):
        price_cents = _to_cents(raw.get(key))
        if price_cents:
            break
    if not price_cents:
        return None
    url = raw.get("canonicalUrl") or raw.get("itemUrl") or raw.get("url") or raw.get("link")
    specifics = raw.get("itemSpecifics") or raw.get("specifics") or {}
    if isinstance(specifics, list):
        specifics = {
            str(entry.get("name") or entry.get("key")): entry.get("value")
            for entry in specifics
            if isinstance(entry, dict)
        }
    return CompRecord(
        title=str(title).strip(),
        price_cents=price_cents,
        kind=kind,
        source=source,
        url=str(url) if url else None,
        condition=(raw.get("condition") or raw.get("conditionText") or None),
        sold_at=(raw.get("soldDate") or raw.get("soldDateText") or raw.get("endDate") or None),
        image_url=(raw.get("imageUrl") or raw.get("image") or raw.get("thumbnail") or None),
        specifics=specifics if isinstance(specifics, dict) else {},
    )


def slugify(query: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", query.lower()).strip("-")


class FixtureCompsSource:
    """Offline comps from JSON fixtures, labeled as such in every source row."""

    name = "fixture"

    def __init__(self, directory: Path | None = None) -> None:
        self.directory = directory or FIXTURE_DIR

    def _load(self, query: str) -> dict[str, Any] | None:
        slug = slugify(query)
        best: tuple[int, Path] | None = None
        for path in self.directory.glob("*.json"):
            stem_tokens = set(path.stem.split("-"))
            overlap = len(stem_tokens & set(slug.split("-")))
            if overlap and (best is None or overlap > best[0]):
                best = (overlap, path)
        if best is None:
            return None
        return json.loads(best[1].read_text())

    async def search(self, query: str, *, kind: CompKind, max_results: int) -> list[CompRecord]:
        data = self._load(query)
        if not data:
            return []
        rows = data.get(kind, [])
        records = [normalize_record(row, kind=kind, source=self.name) for row in rows]
        return [record for record in records if record is not None][:max_results]


def record_dicts(records: list[CompRecord]) -> list[dict[str, Any]]:
    return [asdict(record) for record in records]
