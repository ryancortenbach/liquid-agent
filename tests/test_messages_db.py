from __future__ import annotations

import sqlite3

from app.channels.messages_db import MessagesDatabase


def make_db(path, rows, *, with_column=True):
    connection = sqlite3.connect(path)
    column = ", destination_caller_id TEXT" if with_column else ""
    connection.execute(f"CREATE TABLE message (guid TEXT, is_from_me INTEGER{column})")
    if with_column:
        connection.executemany("INSERT INTO message VALUES (?, ?, ?)", rows)
    connection.commit()
    connection.close()


def test_destination_comes_from_the_message_row(tmp_path) -> None:
    db_path = tmp_path / "chat.db"
    make_db(
        db_path,
        [
            ("m-1", 0, "liquid@icloud.com"),
            ("m-2", 0, "+16505550100"),
            ("m-3", 0, None),
            ("m-4", 1, "liquid@icloud.com"),
        ],
    )
    db = MessagesDatabase(db_path)
    assert db.available()
    assert db.destination_for_guid("m-1") == "liquid@icloud.com"
    assert db.destination_for_guid("m-2") == "+16505550100"
    assert db.destination_for_guid("m-3") is None
    assert db.destination_for_guid("missing") is None
    assert db.inbound_alias_counts() == [("+16505550100", 1), ("liquid@icloud.com", 1), ("", 1)][
        :3
    ] or sorted(db.inbound_alias_counts()) == sorted(
        [("liquid@icloud.com", 1), ("+16505550100", 1), ("", 1)]
    )


def test_unavailable_when_missing_or_without_the_column(tmp_path) -> None:
    assert MessagesDatabase(tmp_path / "nope.db").available() is False
    legacy = tmp_path / "legacy.db"
    make_db(legacy, [], with_column=False)
    assert MessagesDatabase(legacy).available() is False
