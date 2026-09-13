from __future__ import annotations

import argparse
import secrets
import sqlite3
from pathlib import Path

BLUEBUBBLES_CONFIG = (
    Path.home() / "Library" / "Application Support" / "bluebubbles-server" / "config.db"
)


def read_server_password(database: Path = BLUEBUBBLES_CONFIG) -> str:
    if not database.exists():
        raise RuntimeError("BlueBubbles configuration database was not found")
    with sqlite3.connect(database) as connection:
        row = connection.execute("SELECT value FROM config WHERE name = 'password'").fetchone()
    if row is None or not isinstance(row[0], str) or not row[0]:
        raise RuntimeError("BlueBubbles does not have a saved server password")
    return row[0]


def set_values(content: str, values: dict[str, str]) -> str:
    remaining = dict(values)
    lines: list[str] = []
    for line in content.splitlines():
        if "=" not in line or line.lstrip().startswith("#"):
            lines.append(line)
            continue
        key, _value = line.split("=", 1)
        if key in remaining:
            lines.append(f"{key}={remaining.pop(key)}")
        else:
            lines.append(line)
    if remaining:
        if lines and lines[-1]:
            lines.append("")
        lines.extend(f"{key}={value}" for key, value in remaining.items())
    return "\n".join(lines) + "\n"


def run(*, rotate_webhook_secret: bool = False) -> int:
    env_path = Path(".env")
    if not env_path.exists():
        example = Path(".env.example")
        if not example.exists():
            raise RuntimeError("run this script from the Liquid repository root")
        env_path.write_text(example.read_text())
    content = env_path.read_text()
    existing_secret = next(
        (
            line.partition("=")[2]
            for line in content.splitlines()
            if line.startswith("BB_WEBHOOK_SECRET=") and line.partition("=")[2]
        ),
        None,
    )
    updated = set_values(
        content,
        {
            "BB_SERVER_URL": "http://localhost:1234",
            "BB_PASSWORD": read_server_password(),
            "BB_WEBHOOK_SECRET": (
                secrets.token_urlsafe(32)
                if rotate_webhook_secret
                else existing_secret or secrets.token_urlsafe(32)
            ),
            "BB_WEBHOOK_BASE_URL": "http://127.0.0.1:8000",
        },
    )
    env_path.write_text(updated)
    print("Configured local BlueBubbles connection and webhook authentication")
    return 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Configure Liquid for local BlueBubbles")
    parser.add_argument(
        "--rotate-webhook-secret",
        action="store_true",
        help="replace the webhook secret with a new random value",
    )
    arguments = parser.parse_args()
    raise SystemExit(run(rotate_webhook_secret=arguments.rotate_webhook_secret))
