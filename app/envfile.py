"""Update KEY=value lines in a dotenv file without disturbing anything else."""

from __future__ import annotations

from pathlib import Path


def update_env_file(path: str | Path, values: dict[str, str]) -> Path:
    """Set each key in `values`, replacing an existing line or appending a new one."""
    target = Path(path)
    lines = target.read_text().splitlines() if target.exists() else []
    remaining = dict(values)
    for index, line in enumerate(lines):
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key = stripped.split("=", 1)[0].strip()
        if key.startswith("export "):
            key = key[len("export ") :].strip()
        if key in remaining:
            lines[index] = f"{key}={remaining.pop(key)}"
    for key, value in remaining.items():
        lines.append(f"{key}={value}")
    target.write_text("\n".join(lines) + "\n")
    return target
