"""Show which iMessage addresses this Mac replies from, and lock Liquid to one of them.

    uv run python scripts/imessage_accounts.py                 # list aliases + current policy
    uv run python scripts/imessage_accounts.py --set you@icloud.com   # write BB_ALLOWED_DESTINATION
    uv run python scripts/imessage_accounts.py --recent 20     # dry run: would Liquid answer these?

BlueBubbles answers on the Mac's whole iMessage account: every phone number and email alias that
account can be reached at, every contact, every group chat. This script asks the BlueBubbles server
which aliases existing conversations use (falling back to Messages' own database), then prints
whether the current .env would reply to everyone or only to texts sent to the Liquid alias.
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sqlite3
import sys
from collections import Counter
from pathlib import Path

import httpx

from app.channels.imessage_bluebubbles import GROUP_CHAT_STYLE
from app.channels.seller_router import WILDCARD_ALLOWLIST, canonical_handle, parse_handle_allowlist
from app.config import get_settings
from app.envfile import update_env_file

CHAT_DB = Path.home() / "Library" / "Messages" / "chat.db"


def kind_of(alias: str) -> str:
    return "email" if "@" in alias else "phone"


def mask(alias: str) -> str:
    if "@" in alias:
        user, _, domain = alias.partition("@")
        return f"{user[:2]}…@{domain}"
    return f"{alias[:3]}…{alias[-4:]}" if len(alias) > 7 else alias


async def aliases_from_bluebubbles(server_url: str, password: str) -> Counter[tuple[str, bool]]:
    """(alias, is_group) -> chat count, from the BlueBubbles chat query endpoint."""
    tally: Counter[tuple[str, bool]] = Counter()
    async with httpx.AsyncClient(timeout=20) as client:
        offset = 0
        while True:
            response = await client.post(
                f"{server_url.rstrip('/')}/api/v1/chat/query",
                params={"password": password},
                json={
                    "limit": 500,
                    "offset": offset,
                    "with": ["participants"],
                    "sort": "lastmessage",
                },
            )
            response.raise_for_status()
            chats = response.json().get("data") or []
            for chat in chats:
                alias = (chat.get("lastAddressedHandle") or "").strip().lower()
                is_group = chat.get("style") == GROUP_CHAT_STYLE or ";+;" in str(chat.get("guid"))
                tally[(alias, is_group)] += 1
            if len(chats) < 500:
                break
            offset += 500
    return tally


def aliases_from_chat_db(path: Path = CHAT_DB) -> Counter[tuple[str, bool]]:
    tally: Counter[tuple[str, bool]] = Counter()
    connection = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    try:
        rows = connection.execute(
            "SELECT COALESCE(last_addressed_handle, ''), style, COUNT(*) FROM chat GROUP BY 1, 2"
        ).fetchall()
    finally:
        connection.close()
    for alias, style, count in rows:
        tally[(str(alias).strip().lower(), style == GROUP_CHAT_STYLE)] += count
    return tally


async def recent_messages(server_url: str, password: str, limit: int) -> list[dict]:
    """The last `limit` messages with their chats, serialized in full (not notification mode)."""
    async with httpx.AsyncClient(timeout=20) as client:
        response = await client.post(
            f"{server_url.rstrip('/')}/api/v1/message/query",
            params={"password": password},
            json={"limit": limit, "offset": 0, "sort": "DESC", "with": ["chats"]},
        )
        response.raise_for_status()
        return response.json().get("data") or []


def would_answer(settings, *, sender: str, destination: str | None, is_group: bool) -> str:
    """Apply the webhook's rules to one message and say what Liquid would do."""
    if is_group and not settings.bb_allow_group_chats:
        return "ignore: group chat"
    allowed = (settings.bb_allowed_destination or "").strip()
    if not allowed:
        return "ignore: BB_ALLOWED_DESTINATION blank"
    if canonical_handle(destination or "") != canonical_handle(allowed):
        return f"ignore: sent to {mask(destination) if destination else '(unknown alias)'}"
    allowlist = parse_handle_allowlist(settings.seller_handle)
    if allowlist != WILDCARD_ALLOWLIST and canonical_handle(sender) not in allowlist:
        return "ignore: sender not on SELLER_HANDLE list"
    return "ANSWER"


async def dry_run(settings, limit: int) -> None:
    if not settings.bb_password:
        print("--recent needs BB_PASSWORD (run scripts/configure_bluebubbles_local.py)")
        return
    messages = await recent_messages(settings.bb_server_url, settings.bb_password, limit)
    print(f"\nlast {len(messages)} messages on this Mac, judged by the current .env:")
    for message in messages:
        if message.get("isFromMe"):
            continue
        if message.get("associatedMessageGuid") or message.get("associatedMessageType"):
            continue
        chat = (message.get("chats") or [{}])[0]
        sender = ((message.get("handle") or {}).get("address")) or "?"
        destination = chat.get("lastAddressedHandle")
        is_group = chat.get("style") == GROUP_CHAT_STYLE or ";+;" in str(chat.get("guid") or "")
        text = (message.get("text") or "").replace("\n", " ")[:32]
        verdict = would_answer(settings, sender=sender, destination=destination, is_group=is_group)
        kind = "group" if is_group else "dm"
        print(
            f"  from {mask(sender):<14} to {mask(destination) if destination else '(unknown)':<16} "
            f"{kind:<5} {verdict:<40} {text!r}"
        )


def print_policy(settings, aliases: set[str]) -> str:
    sender = (settings.seller_handle or "").strip() or "*"
    destination = (settings.bb_allowed_destination or "").strip()
    print()
    print(f"SELLER_HANDLE={sender}")
    print(f"BB_ALLOWED_DESTINATION={destination or '(blank)'}")
    print(f"BB_ALLOW_GROUP_CHATS={'true' if settings.bb_allow_group_chats else 'false'}")
    print()
    if sender != "*":
        senders = ", ".join(mask(s.strip()) for s in sender.split(",") if s.strip())
        verdict = f"RESTRICTED: only these senders get replies: {senders}"
        if destination:
            verdict += f", and only when they text {mask(destination)}"
    elif destination:
        verdict = f"RESTRICTED: anyone who texts {mask(destination)} gets a reply; nothing else"
        if canonical_handle(destination) not in {canonical_handle(a) for a in aliases if a}:
            verdict += "\nWARNING: that address is not one this Mac has ever replied from"
    else:
        verdict = (
            "CLOSED: BB_ALLOWED_DESTINATION is blank, so Liquid ignores every text until you run "
            "this script with --set <liquid alias>"
        )
    groups = "answered (risky)" if settings.bb_allow_group_chats else "ignored"
    verdict += f"\nGroup chats: {groups}"
    print(verdict)
    return verdict


async def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--set", dest="set_alias", help="write BB_ALLOWED_DESTINATION to .env")
    parser.add_argument("--recent", type=int, default=0, help="dry-run the last N messages")
    parser.add_argument("--env-file", default=".env")
    args = parser.parse_args(argv)
    settings = get_settings()

    tally: Counter[tuple[str, bool]] | None = None
    source = ""
    if settings.bb_password:
        try:
            tally = await aliases_from_bluebubbles(settings.bb_server_url, settings.bb_password)
            source = f"BlueBubbles at {settings.bb_server_url}"
        except Exception as exc:  # server down or wrong password: fall back to chat.db
            print(f"BlueBubbles query failed ({type(exc).__name__}: {exc}); trying chat.db")
    if tally is None:
        try:
            tally = aliases_from_chat_db()
            source = str(CHAT_DB)
        except sqlite3.OperationalError as exc:
            print(f"cannot read {CHAT_DB}: {exc}")
            print("give your terminal Full Disk Access, or start BlueBubbles and set BB_PASSWORD")
            tally = Counter()

    aliases = {alias for alias, _ in tally if alias}
    if tally:
        print(f"iMessage aliases this Mac replies from (source: {source}):")
        by_alias: dict[str, dict[str, int]] = {}
        for (alias, is_group), count in tally.items():
            row = by_alias.setdefault(alias or "(unknown)", {"dm": 0, "group": 0})
            row["group" if is_group else "dm"] += count
        for alias, counts in sorted(by_alias.items(), key=lambda kv: -sum(kv[1].values())):
            label = kind_of(alias) if alias != "(unknown)" else "?"
            print(
                f"  {mask(alias) if alias != '(unknown)' else alias:<22} {label:<6} "
                f"{counts['dm']:>4} direct chats  {counts['group']:>4} group chats"
            )
        print("the alias with the most direct chats is almost certainly the personal one.")

    if args.set_alias:
        chosen = args.set_alias.strip()
        update_env_file(args.env_file, {"BB_ALLOWED_DESTINATION": chosen})
        os.environ["BB_ALLOWED_DESTINATION"] = chosen
        get_settings.cache_clear()
        settings = get_settings()
        print(f"\nwrote BB_ALLOWED_DESTINATION={mask(chosen)} to {args.env_file}")

    verdict = print_policy(settings, aliases)
    if args.recent:
        await dry_run(settings, args.recent)
    return 0 if verdict.startswith("RESTRICTED") else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main(sys.argv[1:])))
