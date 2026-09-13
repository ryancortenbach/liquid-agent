from __future__ import annotations

import logging
import re
import statistics
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from sqlalchemy import Engine
from sqlmodel import Session

from app.ledger import write_decision
from app.market.fees import instant_quote_cents
from app.models import Item, ItemStatus, ResearchResult
from app.research.sources import CompKind, CompRecord, CompsSource

log = logging.getLogger(__name__)

STOPWORDS = {
    "the", "a", "an", "and", "with", "for", "of", "in", "new", "used", "good", "great",
    "condition", "excellent", "fast", "free", "shipping", "sell", "list", "this", "these",
    "item", "from", "imessage", "by", "sunday", "monday", "tuesday", "wednesday", "thursday",
    "friday", "saturday", "week", "day", "days", "please",
}
# Listings that are never a comp for the item itself.
NEGATIVE_PHRASES = (
    "for parts", "parts only", "not working", "broken", "cracked", "damaged", "read description",
    "box only", "empty box", "lot of", "bundle of", "replacement", "repair", "icloud locked",
    "activation lock",
)
# Accessory listings: excluded when pricing a main product, kept when the item IS an accessory.
ACCESSORY_PHRASES = (
    "case", "cover", "sleeve", "skin", "screen protector", "charger", "cable", "adapter",
    "stand", "keyboard", "pencil", "mount",
)
SOLD_HAIRCUT = 0.92
MIN_GROUP = 5
MAX_SOURCES = 6


@dataclass(frozen=True, slots=True)
class CompsSummary:
    query: str
    sold_n: int
    active_n: int
    sold_median_cents: int | None
    active_median_cents: int | None
    market_value_cents: int
    sigma_cents: int
    basis: str
    sources: list[dict[str, Any]] = field(default_factory=list)
    specifics: dict[str, Any] = field(default_factory=dict)
    kept: list[CompRecord] = field(default_factory=list)


MODEL_CODE = re.compile(r"^[a-z]{1,2}\d{3,}[a-z]?$")
ORDINAL = re.compile(r"^(\d+)(st|nd|rd|th)$")
SYNONYMS = {"generation": "gen", "wi": "wifi", "fi": "", "gb": ""}


def _normalize_token(token: str) -> str:
    token = SYNONYMS.get(token, token)
    match = ORDINAL.match(token)
    return match.group(1) if match else token


def query_tokens(text: str) -> set[str]:
    text = text.lower().replace("wi-fi", "wifi").replace("-", "")
    tokens = {_normalize_token(token) for token in re.findall(r"[a-z0-9]+", text)}
    return {token for token in tokens if len(token) > 1 and token not in STOPWORDS}


def core_tokens(tokens: set[str]) -> set[str]:
    """Tokens that must overlap; model codes such as A2588 are a bonus, not a requirement."""
    return {token for token in tokens if not MODEL_CODE.match(token)} or tokens


def build_query(item: Item) -> str:
    seen: list[str] = []
    for part in (item.brand, item.model, item.title):
        for token in re.findall(r"[A-Za-z0-9\-]+", part or ""):
            lowered = token.lower()
            if lowered in STOPWORDS or lowered in {t.lower() for t in seen}:
                continue
            seen.append(token)
    return " ".join(seen[:8]) or item.title


def is_accessory_query(query: str) -> bool:
    lowered = query.lower()
    return any(phrase in lowered for phrase in ACCESSORY_PHRASES)


def is_relevant(record: CompRecord, tokens: set[str], *, accessory: bool = False) -> bool:
    title = record.title.lower()
    if any(phrase in title for phrase in NEGATIVE_PHRASES):
        return False
    if not accessory and any(phrase in title for phrase in ACCESSORY_PHRASES):
        return False
    required = core_tokens(tokens)
    if not required:
        return True
    overlap = len(required & query_tokens(record.title)) / len(required)
    return overlap >= (0.6 if len(required) >= 3 else 0.5)


def _trim_outliers(records: list[CompRecord]) -> list[CompRecord]:
    if len(records) < 4:
        return records
    median = statistics.median(record.price_cents for record in records)
    return [record for record in records if 0.35 * median <= record.price_cents <= 3 * median]


def _sigma(prices: list[int], market: int) -> int:
    floor = max(int(market * 0.08), 100)
    if len(prices) < 3:
        return max(int(market * 0.15), floor)
    median = statistics.median(prices)
    mad = statistics.median(abs(price - median) for price in prices)
    return max(int(1.4826 * mad), floor)


PRIOR_BAND = 4  # comps outside [prior/4, prior*4] are a different product, a lot, or a bundle


def analyze(
    query: str,
    records: list[CompRecord],
    *,
    provisional_cents: int | None = None,
    prior_cents: int | None = None,
    haircut: float = SOLD_HAIRCUT,
) -> CompsSummary:
    tokens = query_tokens(query)
    accessory = is_accessory_query(query)
    relevant = [record for record in records if is_relevant(record, tokens, accessory=accessory)]
    if prior_cents:
        low, high = prior_cents // PRIOR_BAND, prior_cents * PRIOR_BAND
        relevant = [record for record in relevant if low <= record.price_cents <= high]
    sold = _trim_outliers([r for r in relevant if r.kind == "sold"])
    active = _trim_outliers([r for r in relevant if r.kind == "active"])
    sold_prices = [r.price_cents for r in sold]
    active_prices = [r.price_cents for r in active]
    sold_median = int(statistics.median(sold_prices)) if sold_prices else None
    active_median = int(statistics.median(active_prices)) if active_prices else None

    if sold_median is not None and len(sold) >= MIN_GROUP:
        market, basis, spread_prices = sold_median, "sold", sold_prices
    elif active_median is not None and len(active) >= MIN_GROUP:
        market, basis, spread_prices = int(active_median * haircut), "active", active_prices
    elif sold_median is not None or active_median is not None:
        market = sold_median or int((active_median or 0) * haircut)
        basis, spread_prices = "thin", sold_prices or active_prices
    elif prior_cents:
        market, basis, spread_prices = prior_cents, "prior", []
    else:
        market = max(int(provisional_cents or 0), 2_000)
        basis, spread_prices = "provisional", []
    market = max(market, 100)
    sigma = _sigma(spread_prices, market)
    if basis == "prior":
        sigma = max(int(market * 0.25), sigma)

    ordered = sorted(sold, key=lambda r: r.sold_at or "", reverse=True) + active
    sources = [record.to_source() for record in ordered if record.url][:MAX_SOURCES]
    specifics: dict[str, Any] = {}
    for record in ordered[:10]:
        for key, value in record.specifics.items():
            specifics.setdefault(key, value)
    return CompsSummary(
        query=query,
        sold_n=len(sold),
        active_n=len(active),
        sold_median_cents=sold_median,
        active_median_cents=active_median,
        market_value_cents=market,
        sigma_cents=sigma,
        basis=basis,
        sources=sources,
        specifics=specifics,
        kept=sold + active,
    )


async def gather_comps(
    query: str, sources: list[CompsSource], *, max_results: int = 25
) -> list[CompRecord]:
    records: list[CompRecord] = []
    for source in sources:
        kind: CompKind
        for kind in ("sold", "active"):
            try:
                records.extend(await source.search(query, kind=kind, max_results=max_results))
            except Exception as exc:  # one failing source must not sink the research step
                log.warning("comps source %s failed for %s: %s", source.name, kind, exc)
    return records


async def research_item(
    *,
    engine: Engine,
    item_id: str,
    sources: list[CompsSource],
    now: datetime,
    wall_at: datetime,
    max_results: int = 25,
) -> ResearchResult:
    with Session(engine) as session:
        item = session.get(Item, item_id)
        if item is None:
            raise LookupError("item not found")
        query = build_query(item)
        provisional = item.market_value_cents
        prior_info = item.constraints_json.get("price_prior") or {}
        prior = int(prior_info.get("cents") or 0) or None
        category = item.category

    records = await gather_comps(query, sources, max_results=max_results)
    summary = analyze(query, records, provisional_cents=provisional, prior_cents=prior)

    with Session(engine) as session:
        item = session.get(Item, item_id)
        if item is None:
            raise LookupError("item not found")
        result = ResearchResult(
            item_id=item.id,
            query=query,
            sold_n=summary.sold_n,
            active_n=summary.active_n,
            sold_median_cents=summary.sold_median_cents,
            active_median_cents=summary.active_median_cents,
            market_value_cents=summary.market_value_cents,
            sigma_cents=summary.sigma_cents,
            basis=summary.basis,
            sources_json=summary.sources,
            specifics_json=summary.specifics,
            created_at=now,
        )
        session.add(result)
        before = item.market_value_cents
        item.market_value_cents = summary.market_value_cents
        item.sigma_cents = summary.sigma_cents
        item.comps_n = summary.sold_n + summary.active_n
        item.instant_quote_cents = instant_quote_cents(summary.market_value_cents, category)
        item.constraints_json = {**item.constraints_json, "needs_market_data": False}
        if item.status in {ItemStatus.DRAFT, ItemStatus.IDENTIFIED}:
            item.status = ItemStatus.PRICED
        session.add(item)
        write_decision(
            session,
            item_id=item.id,
            sim_at=now,
            wall_at=wall_at,
            kind="system",
            action="research",
            inputs={
                "query": query,
                "sold_n": summary.sold_n,
                "active_n": summary.active_n,
                "sold_median_cents": summary.sold_median_cents,
                "active_median_cents": summary.active_median_cents,
                "basis": summary.basis,
                "sources": summary.sources,
            },
            reason=(
                f"market value from {summary.basis} comps: "
                f"{summary.sold_n} sold, {summary.active_n} active"
            ),
            price_before=before,
            price_after=summary.market_value_cents,
        )
        session.commit()
        session.refresh(result)
        return result
