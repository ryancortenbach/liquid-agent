from __future__ import annotations

import asyncio
from urllib.parse import quote

from app.channels.imessage_bluebubbles import BlueBubblesAdapter
from app.config import get_settings


async def run() -> int:
    settings = get_settings()
    missing = [
        name
        for name, value in (
            ("BB_PASSWORD", settings.bb_password),
            ("BB_WEBHOOK_SECRET", settings.bb_webhook_secret),
            ("SELLER_HANDLE", settings.seller_handle),
        )
        if not value
    ]
    if missing:
        print(f"Missing configuration: {', '.join(missing)}")
        return 1

    adapter = BlueBubblesAdapter(settings.bb_server_url, settings.bb_password or "")
    try:
        await adapter.ping()
        base_url = settings.public_base_url.rstrip("/")
        encoded_secret = quote(settings.bb_webhook_secret or "", safe="")
        webhook_url = f"{base_url}/webhooks/bluebubbles?secret={encoded_secret}"
        result = await adapter.register_webhook(webhook_url)
    finally:
        await adapter.close()

    if result["registered"]:
        print("BlueBubbles new-message webhook registered")
    else:
        print("BlueBubbles new-message webhook was already registered")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(run()))
