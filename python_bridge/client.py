"""Tiny Python client for the bridge (used by demo orchestration / tests)."""
from __future__ import annotations

import json
import urllib.request


def post(endpoint: str, payload: dict, host: str = "127.0.0.1",
         port: int = 8765, timeout: float = 2.0) -> dict:
    url = f"http://{host}:{port}{endpoint}"
    data = json.dumps(payload).encode()
    req = urllib.request.Request(url, data=data,
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read())


def health(host: str = "127.0.0.1", port: int = 8765, timeout: float = 1.0) -> bool:
    try:
        with urllib.request.urlopen(f"http://{host}:{port}/health",
                                    timeout=timeout) as resp:
            return resp.status == 200
    except Exception:
        return False
