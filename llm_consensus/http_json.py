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

# How much of a failing response body to keep for classification. Bounded so a
# large error page cannot bloat a log line or a persisted row, wide enough that
# a provider's error type/status field survives (both sit past the 200-char
# message cut that hid them during the 2026-07-27 wide run).
MAX_ERROR_TEXT = 4000


class LLMHTTPError(RuntimeError):
    """Any failure talking to a provider (network, non-2xx, bad body).

    CARRIES THE OUTCOME IT MEASURED, NOT JUST A SENTENCE (2026-07-27). The
    message stays truncated at 200 characters so logs stay bounded, but a
    truncated sentence is not enough to classify a failure: for both providers
    that ran dry in the wide council run, the field distinguishing a billing
    exhaustion from a rate limit (OpenAI ``error.type``, Gemini
    ``error.status``) sits AFTER the message and was cut off. The retry policy
    therefore saw only the status code and retried a certain second failure.

    ``status``, ``body`` and ``text`` are populated on every HTTP failure so
    ``provider_health.classify`` reads fields instead of a truncated string.
    All three are optional, so an exception built from a bare message (which
    the existing tests do) behaves exactly as before.
    """

    def __init__(self, message: str, *, status: int | None = None,
                 body: dict | None = None, text: str = "") -> None:
        super().__init__(message)
        self.status = status if isinstance(status, int) else None
        self.body = body if isinstance(body, dict) else None
        self.text = str(text or "")


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
        # The MESSAGE stays at 200 characters for bounded logs. The structured
        # fields carry enough to classify the failure, because the field that
        # separates a billing exhaustion from a rate limit sits past that cut.
        raw = resp.text or ""
        try:
            parsed = resp.json()
        except Exception:  # noqa: BLE001 - an unparseable body is still evidence
            parsed = None
        raise LLMHTTPError(
            f"HTTP {resp.status_code}: {raw[:200]}",
            status=resp.status_code,
            body=parsed if isinstance(parsed, dict) else None,
            text=raw[:MAX_ERROR_TEXT])

    try:
        return resp.json()
    except Exception as e:
        raise LLMHTTPError(f"non-JSON response: {e}") from e


# Keys that mark an object as an actual verdict/gate reply, so when a response
# contains several JSON objects (a thinking model's reasoning plus the answer)
# the answer is preferred over an incidental object in the reasoning text.
_VERDICT_HINTS = ("direction", "confidence", "edge", "bias", "proceed", "review")


def extract_json_object(text: str) -> dict | None:
    """Best-effort parse of a single JSON object from real model output.

    Robust to how the providers actually respond: clean JSON, JSON wrapped in
    prose or reasoning text, JSON in markdown code fences, leading or trailing
    commentary, and a trailing stray brace or extra data after a complete object
    (observed from Gemini 3.1 Pro preview, which emits a valid object followed by
    an extra ``}``). It decodes the FIRST complete JSON object at each ``{`` and
    ignores anything after it, then prefers the object that looks like a verdict.
    Returns None when nothing parseable is found (the caller then flat-fallbacks).
    """
    if not text:
        return None
    # Fast path: the whole body is a clean JSON object.
    try:
        obj = json.loads(text)
        if isinstance(obj, dict):
            return obj
    except Exception:
        pass
    # Scan for every complete JSON object, tolerant of trailing junk and prose.
    dec = json.JSONDecoder()
    objs: list[dict] = []
    i = 0
    while True:
        j = text.find("{", i)
        if j == -1:
            break
        try:
            obj, end = dec.raw_decode(text[j:])
            if isinstance(obj, dict):
                objs.append(obj)
            i = j + max(end, 1)
        except Exception:
            i = j + 1
    if objs:
        for obj in objs:
            if any(k in obj for k in _VERDICT_HINTS):
                return obj
        # A thinking model's real answer usually comes last after its reasoning.
        return objs[-1]
    # Nothing decoded cleanly. Gemini 3.1 Pro preview sometimes drops its closing
    # brace (finishReason STOP, not truncation), so try to close an unterminated
    # object from the first "{". If it still will not parse, fall back to None.
    start = text.find("{")
    if start != -1:
        return _repair_object(text[start:])
    return None


def _repair_object(fragment: str) -> dict | None:
    """Close a JSON object a model left unterminated (a missing closing brace, or
    a dangling comma) and parse it. Only the trailing structure is repaired, the
    key/value content is untouched, so a complete-but-unclosed verdict is
    recovered and a truly broken body still returns None."""
    in_str = esc = False
    stack: list[str] = []
    for ch in fragment:
        if esc:
            esc = False
            continue
        if in_str:
            if ch == "\\":
                esc = True
            elif ch == '"':
                in_str = False
            continue
        if ch == '"':
            in_str = True
        elif ch in "{[":
            stack.append(ch)
        elif ch in "}]" and stack:
            stack.pop()
    if not stack and not in_str:
        return None  # balanced already: raw_decode would have parsed it
    repaired = fragment + ('"' if in_str else "")
    repaired = repaired.rstrip()
    while repaired.endswith(","):
        repaired = repaired[:-1].rstrip()
    for opener in reversed(stack):
        repaired += "}" if opener == "{" else "]"
    try:
        obj = json.loads(repaired)
        return obj if isinstance(obj, dict) else None
    except Exception:
        return None
