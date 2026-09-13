"""Mint the eBay refresh token Liquid needs, without a public callback URL.

    uv run python scripts/ebay_authorize.py              # opens the consent page, waits for a paste
    uv run python scripts/ebay_authorize.py --no-browser # print the URL only
    uv run python scripts/ebay_authorize.py --print      # show the token instead of writing .env

Sign in on eBay with the sandbox test user, approve, and paste the URL you land on (the page
itself may fail to load; only the `code=` in the address bar matters). The refresh token is written
to .env as EBAY_SB_REFRESH_TOKEN, which is what the app's single-seller publisher reads.
"""

from __future__ import annotations

import argparse
import asyncio
import secrets
import sys
import webbrowser
from urllib.parse import parse_qs, unquote, urlparse

from app.config import get_settings
from app.envfile import update_env_file
from app.market.ebay_oauth import EbayOAuthClient


def code_from_paste(pasted: str) -> str:
    text = pasted.strip()
    if "code=" in text:
        query = urlparse(text).query if "://" in text else text.split("?", 1)[-1]
        codes = parse_qs(query).get("code")
        if codes:
            return codes[0]
    return unquote(text)


async def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--no-browser", action="store_true", help="do not open the consent page")
    parser.add_argument("--print", action="store_true", help="print the token instead of .env")
    parser.add_argument("--env-file", default=".env")
    args = parser.parse_args(argv)

    settings = get_settings()
    sandbox = settings.ebay_environment == "sandbox"
    client_id = settings.ebay_sb_client_id if sandbox else settings.ebay_client_id
    client_secret = settings.ebay_sb_client_secret if sandbox else settings.ebay_client_secret
    runame = settings.ebay_sb_runame if sandbox else settings.ebay_runame
    prefix = "EBAY_SB" if sandbox else "EBAY"
    if not (client_id and client_secret and runame):
        print(
            f"set {prefix}_CLIENT_ID, {prefix}_CLIENT_SECRET, and {prefix}_RUNAME in .env first "
            "(developer.ebay.com > Application Keys > User Tokens > Get a Token from eBay via "
            "Your Application > Add eBay Redirect URL)."
        )
        return 2

    oauth = EbayOAuthClient(client_id, client_secret, runame, environment=settings.ebay_environment)
    try:
        url = oauth.authorization_url(secrets.token_urlsafe(12))
        print(f"1. Sign in and approve here ({settings.ebay_environment}):\n\n{url}\n")
        if not args.no_browser:
            webbrowser.open(url)
        pasted = input("2. Paste the URL you landed on (or just the code): ")
        code = code_from_paste(pasted)
        if not code:
            print("no authorization code found in the paste")
            return 1
        tokens = await oauth.exchange_code(code)
    finally:
        await oauth.close()

    print(f"\nscopes granted: {' '.join(s.rsplit('/', 1)[-1] for s in tokens.scopes)}")
    if args.print or not sandbox:
        print(f"{prefix}_REFRESH_TOKEN={tokens.refresh_token}")
        if not sandbox:
            print("(production tokens are stored per seller by the CONNECT EBAY flow, not .env)")
        return 0
    update_env_file(args.env_file, {"EBAY_SB_REFRESH_TOKEN": tokens.refresh_token})
    masked = tokens.refresh_token[:8] + "…" + tokens.refresh_token[-4:]
    print(f"wrote EBAY_SB_REFRESH_TOKEN={masked} to {args.env_file}")
    print("next: uv run python scripts/ebay_setup.py")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main(sys.argv[1:])))
