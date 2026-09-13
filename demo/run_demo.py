"""Drive the seller flow over the API for rehearsal and the backup take.

    uv run python demo/run_demo.py --photo path/to/ipad.jpg --title "Apple iPad Air 5th gen 64GB" \
        --details "2, comes with the box and charger, small scratch on the back" \
        --plan "3 days, not under 220, both 94110, all" --skip-hours 30

Requires the server: `uv run uvicorn app.main:app`. Photo enhancement needs OPENAI_API_KEY; without
it the script continues without photos (eBay will refuse, handoffs still work).
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import httpx


def step(label: str, response: httpx.Response) -> dict:
    body = response.json() if response.content else {}
    print(f"[{response.status_code}] {label}")
    if response.status_code >= 400:
        print("   ", body.get("detail", body))
    return body if isinstance(body, dict) else {"data": body}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default="http://localhost:8000")
    parser.add_argument("--photo", type=Path)
    parser.add_argument("--title", default="Apple iPad Air 5th gen 64GB Wi-Fi")
    parser.add_argument("--brand", default="Apple")
    parser.add_argument("--floor", type=int, default=22_000, help="cents")
    parser.add_argument("--deadline-hours", type=float, default=72)
    parser.add_argument("--details", default="2, comes with the box and charger, small scratch on the back")
    parser.add_argument("--plan", default="3 days, not under 220, both 94110, all")
    parser.add_argument("--skip-hours", type=float, default=30)
    parser.add_argument("--no-go", action="store_true")
    args = parser.parse_args()

    with httpx.Client(base_url=args.base_url, timeout=180) as client:
        created = step(
            "create item",
            client.post(
                "/api/items",
                json={
                    "seller_handle": "+14155550123",
                    "title": args.title,
                    "brand": args.brand,
                    "market_value_cents": max(args.floor * 4 // 3, 10_000),
                    "sigma_cents": max(args.floor // 8, 1_000),
                    "floor_cents": args.floor,
                    "deadline_hours": args.deadline_hours,
                },
            ),
        )
        item_id = created["item_id"]
        print("    dashboard:", f"{args.base_url}/dashboard/{item_id}")

        if args.photo:
            with args.photo.open("rb") as handle:
                enhanced = step(
                    "enhance photo",
                    client.post(
                        f"/api/items/{item_id}/photos/enhance",
                        files={"upload": (args.photo.name, handle, "image/jpeg")},
                        data={"preset": "studio"},
                    ),
                )
            if "enhanced_photo_id" in enhanced:
                step(
                    "approve enhanced photo",
                    client.post(
                        f"/api/items/{item_id}/photos/{enhanced['enhanced_photo_id']}/review",
                        json={"approved": True},
                    ),
                )

        step("details 1", client.post(f"/api/items/{item_id}/details", json={"text": args.details}))
        step("details 2", client.post(f"/api/items/{item_id}/details", json={"text": args.plan}))
        plan = step(
            "plan listing", client.post(f"/api/items/{item_id}/plan-listing", json={"research": True})
        )
        print(plan.get("card_text", ""))
        if args.no_go:
            return 0
        outcome = step("go", client.post(f"/api/items/{item_id}/go"))
        print(json.dumps(outcome.get("outcomes", {}), indent=2))
        if args.skip_hours:
            step("skip clock", client.post("/api/clock/skip", json={"hours": args.skip_hours}))
            reprice = step("reprice", client.post(f"/api/items/{item_id}/reprice"))
            print(json.dumps(reprice, indent=2))
        packs = step("packs", client.get(f"/api/items/{item_id}/packs"))
        for pack in packs.get("data", []):
            print(f"    {pack['channel']:<10} {pack['status']:<14} ${pack['price_cents'] / 100:.0f}",
                  pack.get("external_url") or pack.get("handoff_path") or pack.get("failure_reason"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
