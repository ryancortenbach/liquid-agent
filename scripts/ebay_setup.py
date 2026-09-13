"""Make the eBay sandbox seller publish-ready in one command.

    uv run python scripts/ebay_setup.py
    uv run python scripts/ebay_setup.py --zip 10001 --city "New York" --state NY
    uv run python scripts/ebay_setup.py --no-write     # print the env lines instead of editing .env

Opts the seller into business policies, creates (or finds) the payment, return, and fulfillment
policies and a ship-from location, then writes their ids into .env. Safe to re-run.
"""

from __future__ import annotations

import argparse
import asyncio
import sys

from app.config import get_settings
from app.envfile import update_env_file
from app.market.ebay import EbayError
from app.market.ebay_setup import EbayAccountClient


async def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--zip", default="94105", help="ship-from ZIP (default 94105)")
    parser.add_argument("--city", default="San Francisco")
    parser.add_argument("--state", default="CA")
    parser.add_argument("--country", default="US")
    parser.add_argument("--location-key", default=None, help="merchant location key")
    parser.add_argument("--prefix", default="Liquid", help="policy name prefix")
    parser.add_argument("--no-write", action="store_true", help="do not edit .env")
    parser.add_argument("--env-file", default=".env")
    args = parser.parse_args(argv)

    settings = get_settings()
    missing = [
        name
        for name, value in {
            "EBAY_SB_CLIENT_ID": settings.ebay_sb_client_id,
            "EBAY_SB_CLIENT_SECRET": settings.ebay_sb_client_secret,
            "EBAY_SB_REFRESH_TOKEN": settings.ebay_sb_refresh_token,
        }.items()
        if not value
    ]
    if missing:
        print(f"missing in .env: {', '.join(missing)}")
        print("run: uv run python scripts/ebay_authorize.py")
        return 2

    client = EbayAccountClient(
        settings.ebay_sb_client_id or "",
        settings.ebay_sb_client_secret or "",
        settings.ebay_sb_refresh_token or "",
        environment="sandbox",
    )
    try:
        setup = await client.ensure_seller_setup(
            marketplace_id=settings.ebay_marketplace_id,
            location_key=(
                args.location_key or settings.ebay_sb_merchant_location_key or "liquid-home"
            ),
            policy_prefix=args.prefix,
            postal_code=args.zip,
            city=args.city,
            state=args.state,
            country=args.country,
        )
    except EbayError as exc:
        print(f"eBay refused: {exc}")
        if exc.error_id == 20403 or "polic" in str(exc).lower():
            print("business policies are not active for this seller yet; retry in a few minutes")
        return 1
    finally:
        await client.close()

    print("business policies: opted in")
    print(f"created this run: {', '.join(setup.created) or 'nothing (everything existed)'}")
    for key, value in setup.env_values().items():
        print(f"{key}={value}")
    if not args.no_write:
        update_env_file(args.env_file, setup.env_values())
        print(f"wrote those four lines to {args.env_file}")
    print("next: uv run python scripts/ebay_verify.py --draft")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main(sys.argv[1:])))
