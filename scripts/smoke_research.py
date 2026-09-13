"""Check the comps sources with the configured keys: `uv run python scripts/smoke_research.py "iPad Air 5th gen 64GB"`."""

from __future__ import annotations

import asyncio
import sys

from app.config import get_settings
from app.research.comps import analyze, gather_comps
from app.research.factory import build_comps_sources


async def main(query: str) -> int:
    settings = get_settings()
    sources = build_comps_sources(settings)
    print(f"research_mode={settings.research_mode} sources={[source.name for source in sources]}")
    for source in sources:
        for kind in ("sold", "active"):
            try:
                records = await source.search(query, kind=kind, max_results=25)
                print(f"  {source.name:<18} {kind:<6} {len(records):>3} records")
            except Exception as exc:
                print(f"  {source.name:<18} {kind:<6} ERROR {exc}")
    records = await gather_comps(query, sources)
    summary = analyze(query, records)
    print(
        f"basis={summary.basis} sold_n={summary.sold_n} active_n={summary.active_n} "
        f"M=${summary.market_value_cents / 100:.0f} sigma=${summary.sigma_cents / 100:.0f}"
    )
    for source in summary.sources[:5]:
        print(f"  {source['kind']:<6} ${source['price_cents'] / 100:>7.0f}  {source['title'][:60]}")
    return 0 if records else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main(" ".join(sys.argv[1:]) or "Apple iPad Air 5th gen 64GB Wi-Fi")))
