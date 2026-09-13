"""Read the exact addressed alias of an inbound iMessage from Messages' own database.

A 1:1 iMessage chat is keyed by the other person's handle, so a friend who texts the Mac owner's
phone number and a tester who texts the Liquid email can land in the same chat row. The chat-level
`lastAddressedHandle` therefore cannot separate them, but each `message` row records which of our
aliases it was sent to in `destination_caller_id`. BlueBubbles does not expose that column, and
Liquid runs on the same Mac, so read it directly (read-only; needs Full Disk Access for the
terminal that runs Liquid).
"""

from __future__ import annotations

import logging
import sqlite3
from pathlib import Path

log = logging.getLogger(__name__)

DEFAULT_CHAT_DB = Path.home() / "Library" / "Messages" / "chat.db"


class MessagesDatabase:
    def __init__(self, path: str | Path = DEFAULT_CHAT_DB) -> None:
        self.path = Path(path).expanduser()

    def _connect(self) -> sqlite3.Connection:
        return sqlite3.connect(f"file:{self.path}?mode=ro", uri=True, timeout=2)

    def available(self) -> bool:
        """True when the database is readable and has the per-message destination column."""
        if not self.path.exists():
            return False
        try:
            connection = self._connect()
        except sqlite3.Error:
            return False
        try:
            columns = {row[1] for row in connection.execute("PRAGMA table_info(message)")}
        except sqlite3.Error:
            return False
        finally:
            connection.close()
        return "destination_caller_id" in columns

    def destination_for_guid(self, message_guid: str) -> str | None:
        """Which of our aliases the message with this guid was addressed to, or None."""
        connection = self._connect()
        try:
            row = connection.execute(
                "SELECT destination_caller_id FROM message WHERE guid = ? LIMIT 1", (message_guid,)
            ).fetchone()
        finally:
            connection.close()
        if row is None or not isinstance(row[0], str) or not row[0].strip():
            return None
        return row[0].strip().lower()

    def inbound_alias_counts(self) -> list[tuple[str, int]]:
        """(alias, inbound message count): the addresses people actually text this Mac at."""
        connection = self._connect()
        try:
            rows = connection.execute(
                "SELECT COALESCE(destination_caller_id, ''), COUNT(*) FROM message "
                "WHERE is_from_me = 0 GROUP BY 1 ORDER BY 2 DESC"
            ).fetchall()
        finally:
            connection.close()
        return [(str(alias).strip().lower(), int(count)) for alias, count in rows]
