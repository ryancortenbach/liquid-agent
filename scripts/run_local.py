from __future__ import annotations

import argparse
import logging

import uvicorn


def main() -> int:
    parser = argparse.ArgumentParser(description="Run Liquid without logging webhook secrets")
    parser.add_argument("--reload", action="store_true")
    arguments = parser.parse_args()
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    logging.getLogger("app").setLevel(logging.INFO)
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
