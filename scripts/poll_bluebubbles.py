"""Pull new iMessages from BlueBubbles and feed them to Liquid's webhook.

BlueBubbles webhook delivery stalls after the backend restarts, and messages
sent in the gap are never replayed. This poller asks BlueBubbles for recent
messages every couple of seconds and posts anything new to the same webhook
endpoint, so every gate, dedupe check, and router runs exactly as it would for
a pushed event. Messages the webhook already saw are rejected as duplicates by
their GUID, so running this alongside the webhook is safe.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from pathlib import Path
from urllib.parse import quote

import httpx

from app.config import get_settings

log = logging.getLogger("poll_bluebubbles")

STATE_PATH = Path("logs/poll_bluebubbles.state.json")
POLL_SECONDS = 2.0
LOOKBACK_MS = 10 * 60 * 1000
PAGE = 25


def load_last_seen() -> int:
    try:
        return int(json.loads(STATE_PATH.read_text())["last_seen_ms"])
    except (OSError, ValueError, KeyError):
        return int(time.time() * 1000) - LOOKBACK_MS


def save_last_seen(value: int) -> None:
    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    STATE_PATH.write_text(json.dumps({"last_seen_ms": value}))


async def run() -> int:
    settings = get_settings()
    if not settings.bb_password or not settings.bb_webhook_secret:
        print("Missing BB_PASSWORD or BB_WEBHOOK_SECRET")
        return 1
    server = settings.bb_server_url.rstrip("/")
    webhook = (
        f"{settings.bb_webhook_base_url.rstrip('/')}/webhooks/bluebubbles"
        f"?secret={quote(settings.bb_webhook_secret, safe='')}"
    )
    last_seen = load_last_seen()
    log.info("polling %s every %.0fs, starting after %d", server, POLL_SECONDS, last_seen)

    async with httpx.AsyncClient(timeout=15.0) as client:
        while True:
            try:
                response = await client.post(
                    f"{server}/api/v1/message/query",
                    params={"password": settings.bb_password},
                    json={
                        "limit": PAGE,
                        "offset": 0,
                        "with": ["chats", "handle", "attachments"],
                        "sort": "DESC",
                    },
                )
                response.raise_for_status()
                messages = response.json().get("data") or []
                fresh = [
                    message
                    for message in messages
                    if not message.get("isFromMe")
                    and int(message.get("dateCreated") or 0) > last_seen
                ]
                fresh.sort(key=lambda message: int(message.get("dateCreated") or 0))
                for message in fresh:
                    payload = {"type": "new-message", "data": message}
                    result = await client.post(webhook, json=payload)
                    body = result.json() if result.headers.get("content-type", "").startswith(
                        "application/json"
                    ) else {}
                    handle = ((message.get("handle") or {}).get("address") or "")[-4:]
                    log.info(
                        "replayed guid=%s sender=***%s text=%r -> %s %s",
                        (message.get("guid") or "")[:8],
                        handle,
                        (message.get("text") or "")[:40],
                        result.status_code,
                        body.get("status"),
                    )
                    last_seen = max(last_seen, int(message.get("dateCreated") or 0))
                    save_last_seen(last_seen)
            except Exception as exc:  # keep polling through transient errors
                log.warning("poll failed: %s", exc)
            await asyncio.sleep(POLL_SECONDS)


def main() -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    # httpx logs full request URLs, which carry the webhook secret and BlueBubbles password.
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)
    try:
        return asyncio.run(run())
    except KeyboardInterrupt:
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
