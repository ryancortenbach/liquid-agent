from __future__ import annotations

import argparse
import asyncio
from pathlib import Path

from app.channels.imessage_bluebubbles import BlueBubblesAdapter
from app.config import get_settings
from app.db import create_db_and_tables, make_engine


def configured(value: str | None) -> bool:
    return bool(value and value.strip())


async def run(live: bool) -> int:
    settings = get_settings()
    results: list[tuple[str, str, str]] = []

    try:
        engine = make_engine("sqlite:///:memory:")
        create_db_and_tables(engine)
        results.append(("Core database", "PASS", "schema created"))
    except Exception as exc:
        results.append(("Core database", "FAIL", type(exc).__name__))

    if configured(settings.bb_password):
        if live:
            adapter = BlueBubblesAdapter(settings.bb_server_url, settings.bb_password or "")
            try:
                await adapter.ping()
                results.append(("BlueBubbles", "PASS", "ping succeeded"))
            except Exception as exc:
                results.append(("BlueBubbles", "FAIL", type(exc).__name__))
            finally:
                await adapter.close()
        else:
            results.append(("BlueBubbles", "READY", "credentials present"))
    else:
        results.append(("BlueBubbles", "MISSING", "BB_PASSWORD"))

    checks = [
        ("eBay Browse", settings.ebay_client_id and settings.ebay_client_secret, "eBay keys"),
        ("Stripe", settings.stripe_secret_key, "STRIPE_SECRET_KEY"),
        ("Shippo", settings.shippo_api_key, "SHIPPO_API_KEY"),
        ("Claude", settings.anthropic_api_key, "ANTHROPIC_API_KEY"),
    ]
    for name, value, label in checks:
        status = "READY" if configured(value) else "MISSING"
        detail = "credentials present" if status == "READY" else label
        results.append((name, status, detail))

    gcal_ready = Path(settings.google_oauth_client_json).exists()
    results.append(
        (
            "Google Calendar",
            "READY" if gcal_ready else "MISSING",
            "OAuth client present" if gcal_ready else settings.google_oauth_client_json,
        )
    )

    widths = [max(len(row[index]) for row in results) for index in range(3)]
    for name, status, detail in results:
        print(f"{name:<{widths[0]}}  {status:<{widths[1]}}  {detail:<{widths[2]}}")
    return 1 if any(status == "FAIL" for _, status, _ in results) else 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Check Liquid integration readiness")
    parser.add_argument("--live", action="store_true", help="call configured local services")
    args = parser.parse_args()
    return asyncio.run(run(args.live))


if __name__ == "__main__":
    raise SystemExit(main())
