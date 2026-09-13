from __future__ import annotations

import sqlite3
from pathlib import Path

from scripts.configure_bluebubbles_local import read_server_password, set_values


def test_read_server_password(tmp_path: Path) -> None:
    database = tmp_path / "config.db"
    with sqlite3.connect(database) as connection:
        connection.execute("CREATE TABLE config (name TEXT PRIMARY KEY, value TEXT)")
        connection.execute("INSERT INTO config VALUES ('password', 'server-secret')")
    assert read_server_password(database) == "server-secret"


def test_set_values_replaces_and_appends_without_touching_other_keys() -> None:
    original = "BB_SERVER_URL=old\nSELLER_HANDLE=person@example.com\n"
    result = set_values(
        original,
        {
            "BB_SERVER_URL": "http://localhost:1234",
            "BB_WEBHOOK_SECRET": "webhook-secret",
        },
    )
    assert result == (
        "BB_SERVER_URL=http://localhost:1234\n"
        "SELLER_HANDLE=person@example.com\n\n"
        "BB_WEBHOOK_SECRET=webhook-secret\n"
    )
