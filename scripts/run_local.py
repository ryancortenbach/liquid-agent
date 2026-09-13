from __future__ import annotations

import argparse

import uvicorn


def main() -> int:
    parser = argparse.ArgumentParser(description="Run Liquid without logging webhook secrets")
    parser.add_argument("--reload", action="store_true")
    arguments = parser.parse_args()
    uvicorn.run(
        "app.main:app",
        host="127.0.0.1",
        port=8000,
        reload=arguments.reload,
        access_log=False,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
