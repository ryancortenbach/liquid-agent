"""Prove every eBay path Liquid uses, live, in one run.

    uv run python scripts/ebay_verify.py            # read-only: comps, category, auth, policies
    uv run python scripts/ebay_verify.py --draft    # + host a photo on eBay, create a draft offer
    uv run python scripts/ebay_verify.py --publish  # + publish, reprice, then withdraw and clean up

Prints PASS/FAIL/SKIP per step and exits non-zero on any FAIL. Production keys
(EBAY_CLIENT_ID/SECRET) drive comps and category suggestions; the sandbox keyset and refresh
token drive everything else. The --publish run leaves nothing behind in the sandbox.
"""

from __future__ import annotations

import argparse
import asyncio
import io
import sys
import time

from app.config import get_settings
from app.market.ebay import EbayError, EbayOfferInput
from app.market.ebay_setup import SELLING_POLICY_PROGRAM, EbayAccountClient
from app.market.ebay_taxonomy import EbayTaxonomyClient, resolve_category
from app.research.ebay_browse import EbayBrowseSource

QUERY = "Sony WH-1000XM5 headphones"
Result = tuple[str, str, str]


def test_picture() -> bytes:
    from PIL import Image, ImageDraw

    image = Image.new("RGB", (640, 640), (240, 236, 228))
    draw = ImageDraw.Draw(image)
    draw.rectangle((80, 80, 560, 560), outline=(40, 40, 40), width=6)
    draw.text((120, 300), "Liquid sandbox verify", fill=(40, 40, 40))
    buffer = io.BytesIO()
    image.save(buffer, format="JPEG", quality=85)
    return buffer.getvalue()


async def check_comps(settings) -> Result:
    if not (settings.ebay_client_id and settings.ebay_client_secret):
        return ("comps (Browse API)", "SKIP", "set EBAY_CLIENT_ID/SECRET (production keyset)")
    source = EbayBrowseSource(settings.ebay_client_id, settings.ebay_client_secret)
    try:
        records = await source.search(QUERY, kind="active", max_results=25)
    except Exception as exc:
        return ("comps (Browse API)", "FAIL", f"{type(exc).__name__}: {exc}")
    finally:
        await source.close()
    if not records:
        return ("comps (Browse API)", "FAIL", "0 active listings returned")
    sample = records[0]
    return (
        "comps (Browse API)",
        "PASS",
        f"{len(records)} active comps; e.g. ${sample.price_cents / 100:.0f} {sample.title[:40]}",
    )


async def check_category(settings) -> tuple[Result, str]:
    default = settings.ebay_sb_default_category_id
    if not (settings.ebay_client_id and settings.ebay_client_secret):
        resolved = await resolve_category(
            explicit=None, query=QUERY, item_category="headphones", default=default, taxonomy=None
        )
        return (
            ("category (Taxonomy API)", "SKIP", f"no production keys; using {resolved.source} "
             f"{resolved.category_id}"),
            resolved.category_id,
        )
    taxonomy = EbayTaxonomyClient(settings.ebay_client_id, settings.ebay_client_secret)
    try:
        suggestion = await taxonomy.suggest(QUERY)
    except Exception as exc:
        resolved = await resolve_category(
            explicit=None, query=QUERY, item_category="headphones", default=default, taxonomy=None
        )
        return (
            ("category (Taxonomy API)", "FAIL", f"{type(exc).__name__}: {exc}"),
            resolved.category_id,
        )
    finally:
        await taxonomy.close()
    if suggestion is None:
        return ("category (Taxonomy API)", "FAIL", "no suggestion returned"), default or "112529"
    return (
        ("category (Taxonomy API)", "PASS", f"{suggestion.category_id} {suggestion.path}"),
        suggestion.category_id,
    )


async def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--draft", action="store_true", help="create a sandbox draft offer")
    parser.add_argument("--publish", action="store_true", help="publish, reprice, then clean up")
    args = parser.parse_args(argv)
    settings = get_settings()
    results: list[Result] = []

    results.append(await check_comps(settings))
    category_result, category_id = await check_category(settings)
    results.append(category_result)

    sandbox_missing = [
        name
        for name, value in {
            "EBAY_SB_CLIENT_ID": settings.ebay_sb_client_id,
            "EBAY_SB_CLIENT_SECRET": settings.ebay_sb_client_secret,
            "EBAY_SB_REFRESH_TOKEN": settings.ebay_sb_refresh_token,
        }.items()
        if not value
    ]
    if sandbox_missing:
        results.append(("sandbox auth", "SKIP", f"missing {', '.join(sandbox_missing)}"))
        return report(results)

    client = EbayAccountClient(
        settings.ebay_sb_client_id or "",
        settings.ebay_sb_client_secret or "",
        settings.ebay_sb_refresh_token or "",
        environment="sandbox",
    )
    marketplace = settings.ebay_marketplace_id
    try:
        try:
            await client.access_token()
            results.append(("sandbox auth", "PASS", "refresh token minted an access token"))
        except EbayError as exc:
            results.append(("sandbox auth", "FAIL", str(exc)))
            return report(results)

        try:
            programs = await client.opted_in_programs(marketplace)
            opted = SELLING_POLICY_PROGRAM in programs
            results.append(
                ("business policies", "PASS" if opted else "FAIL",
                 "opted in" if opted else "not opted in; run scripts/ebay_setup.py")
            )
        except EbayError as exc:
            results.append(("business policies", "FAIL", str(exc)))

        policies = {
            "payment": settings.ebay_sb_payment_policy_id,
            "return": settings.ebay_sb_return_policy_id,
            "fulfillment": settings.ebay_sb_fulfillment_policy_id,
        }
        for kind, policy_id in policies.items():
            if not policy_id:
                results.append((f"{kind} policy", "FAIL", "id missing; run scripts/ebay_setup.py"))
                continue
            try:
                exists = await client.policy_exists(kind, policy_id, marketplace)
                results.append(
                    (f"{kind} policy", "PASS" if exists else "FAIL",
                     policy_id if exists else f"{policy_id} not found on this seller")
                )
            except EbayError as exc:
                results.append((f"{kind} policy", "FAIL", str(exc)))

        location_key = settings.ebay_sb_merchant_location_key
        if not location_key:
            results.append(("location", "FAIL", "key missing; run scripts/ebay_setup.py"))
        else:
            try:
                exists = await client.location_exists(location_key, marketplace)
                results.append(
                    ("location", "PASS" if exists else "FAIL",
                     location_key if exists else f"{location_key} not found")
                )
            except EbayError as exc:
                results.append(("location", "FAIL", str(exc)))

        if not (args.draft or args.publish):
            return report(results)
        if any(status == "FAIL" for _, status, _ in results[2:]):
            results.append(("draft offer", "SKIP", "fix the failures above first"))
            return report(results)

        sku = f"liquid-verify-{int(time.time())}"
        offer_id: str | None = None
        try:
            picture_url = await client.upload_picture(
                test_picture(), filename="verify.jpg", picture_name="liquid-verify"
            )
            results.append(("photo hosting (EPS)", "PASS", picture_url[:70]))
            draft = await client.create_draft(
                EbayOfferInput(
                    sku=sku,
                    title="Liquid sandbox verification listing (ignore)",
                    description="Automated sandbox check from Liquid. Not a real item.",
                    condition="USED_VERY_GOOD",
                    aspects={"Brand": ["Sony"], "Model": ["WH-1000XM5"]},
                    image_urls=[picture_url],
                    category_id=category_id,
                    marketplace_id=marketplace,
                    currency=settings.ebay_currency,
                    price_cents=19_900,
                    merchant_location_key=location_key or "",
                    payment_policy_id=policies["payment"] or "",
                    return_policy_id=policies["return"] or "",
                    fulfillment_policy_id=policies["fulfillment"] or "",
                )
            )
            offer_id = draft.offer_id
            results.append(("draft offer", "PASS", f"offer {offer_id} (sku {sku})"))
        except EbayError as exc:
            results.append(("draft offer", "FAIL", str(exc)))

        if args.publish and offer_id:
            try:
                publication = await client.publish(offer_id, marketplace)
                results.append(
                    ("publish", "PASS",
                     f"https://www.sandbox.ebay.com/itm/{publication.listing_id}")
                )
                await client.update_price(
                    sku=sku, offer_id=offer_id, price_cents=18_900,
                    currency=settings.ebay_currency, marketplace_id=marketplace,
                )
                results.append(("reprice", "PASS", "$199 -> $189 via bulkUpdatePriceQuantity"))
                await client.withdraw(offer_id, marketplace)
                results.append(("withdraw", "PASS", "listing ended"))
            except EbayError as exc:
                results.append(("publish/reprice", "FAIL", str(exc)))

        if offer_id:
            try:
                await client.delete_offer(offer_id, marketplace)
                await client.delete_inventory_item(sku, marketplace)
                results.append(("cleanup", "PASS", "offer and inventory item deleted"))
            except EbayError as exc:
                results.append(("cleanup", "FAIL", f"delete {sku} by hand: {exc}"))
    finally:
        await client.close()
    return report(results)


def report(results: list[Result]) -> int:
    width = max(len(name) for name, _, _ in results)
    for name, status, detail in results:
        print(f"{name:<{width}}  {status:<4}  {detail}")
    failed = [name for name, status, _ in results if status == "FAIL"]
    print()
    print("eBay: all good" if not failed else f"eBay: fix {', '.join(failed)}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main(sys.argv[1:])))
