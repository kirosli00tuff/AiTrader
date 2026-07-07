"""Entry point: serve the API on loopback via uvicorn.

Run: python -m api_server.run  (or via scripts/run_gui.sh with the frontend).
Binds api_server.app.HOST (127.0.0.1) only.
"""
from __future__ import annotations

import uvicorn

from api_server.app import HOST, PORT


def main() -> None:
    uvicorn.run("api_server.app:app", host=HOST, port=PORT, log_level="info")


if __name__ == "__main__":
    main()
