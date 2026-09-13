from __future__ import annotations

import argparse
import logging
import sys

import uvicorn

from app.channels.messages_db import MessagesDatabase
from app.config import get_settings


def reply_policy_ok() -> bool:
    """Refuse to start until the Liquid iMessage alias is chosen."""
    settings = get_settings()
    sender = (settings.seller_handle or "").strip() or "*"
    destination = (settings.bb_allowed_destination or "").strip()
    print(
        f"reply policy: senders={sender} destination={destination or '(any)'} "
        f"group_chats={'answered' if settings.bb_allow_group_chats else 'ignored'}"
    )
    if destination and destination != "*":
        exact = MessagesDatabase(settings.messages_db_path).available()
        print(
            "destination check: "
            + (
                "exact (per-message alias from Messages' chat.db)"
                if exact
                else "APPROXIMATE (chat-level alias only). iMessage merges a contact's texts to "
                "your number and your email into one thread, so texts to the Liquid address can "
                "be refused. Grant Full Disk Access to Terminal, then restart."
            )
        )
    if not destination:
        print(
            "refusing to start: BB_ALLOWED_DESTINATION is blank, so Liquid would ignore every "
            "text (and without that rule it would answer every conversation on this Mac).\n"
            "run: uv run python scripts/imessage_accounts.py --set <liquid alias>"
        )
        return False
    return True


def main() -> int:
    parser = argparse.ArgumentParser(description="Run Liquid without logging webhook secrets")
    parser.add_argument("--reload", action="store_true")
    arguments = parser.parse_args()
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    logging.getLogger("app").setLevel(logging.INFO)
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpx2").setLevel(logging.WARNING)
    if not reply_policy_ok():
        return 2
    uvicorn.run(
        "app.main:app",
        host="127.0.0.1",
        port=8000,
        reload=arguments.reload,
        access_log=False,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
