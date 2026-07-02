"""One tiny HTTP seam for the real LLM providers.

Every outbound provider call goes through :func:`post_json`. Keeping it in a
single function means tests mock exactly one place (``llm_consensus.http_json``)
and never touch the network. ``requests`` is imported lazily so importing the
council never requires it in a minimal/offline environment.
"""
from __future__ import annotations

import json
import logging
from typing import Any

log = logging.getLogger("llm_consensus")

DEFAULT_TIMEOUT = 20.0


class LLMHTTPError(RuntimeError):
    """Any failure talking to a provider (network, non-2xx, bad body)."""


def post_json(url: str, headers: dict[str, str], payload: dict[str, Any],
              timeout: float = DEFAULT_TIMEOUT) -> dict:
    """POST ``payload`` as JSON, return the parsed JSON response as a dict.

    Raises :class:`LLMHTTPError` on any transport/status/decode failure so the
    caller can uniformly fall back to a flat verdict. Never logs credentials.
    """
    try:
        import requests  # lazy: keeps the council importable without requests
    except Exception as e:  # pragma: no cover - requests is a declared dep
        raise LLMHTTPError(f"requests unavailable: {e}") from e

    try:
        resp = requests.post(url, headers=headers, json=payload, timeout=timeout)
    except Exception as e:
        raise LLMHTTPError(f"request failed: {e}") from e

    if resp.status_code >= 400:
        # Body may carry a provider error message; keep it short, never the key.
        raise LLMHTTPError(f"HTTP {resp.status_code}: {resp.text[:200]}")

    try:
        return resp.json()
    except Exception as e:
        raise LLMHTTPError(f"non-JSON response: {e}") from e


def extract_json_object(text: str) -> dict | None:
    """Best-effort parse of a single JSON object from model output.

    Handles clean JSON and JSON wrapped in stray prose / code fences by slicing
    the outermost ``{ ... }`` span. Returns None when nothing parseable is found.
    """
    if not text:
        return None
    try:
        obj = json.loads(text)
        return obj if isinstance(obj, dict) else None
    except Exception:
        pass
    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end == -1 or end <= start:
        return None
    try:
        obj = json.loads(text[start:end + 1])
        return obj if isinstance(obj, dict) else None
    except Exception:
        return None
