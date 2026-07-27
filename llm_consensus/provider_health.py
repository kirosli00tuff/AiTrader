"""Provider failure classification and the session exhaustion latch.

WHY THIS EXISTS (2026-07-27). The wide council run retried a billing 429 as
though it were a rate limit. GPT-5.5 returned "You exceeded your current quota"
from 03:30 and failed 315 of 389 calls, Gemini the same from 08:16 failing 73,
and every one of those failures was made twice because the retry policy read
only the status code. A quota-exceeded response means the account is out of
credit. The second attempt is a certain second failure.

A 429 CARRIES TWO MEANINGS AND THE STATUS CODE ALONE CANNOT SEPARATE THEM:

  * RATE LIMITED   too many requests just now. Transient, worth one retry.
  * EXHAUSTED      the account is out of quota or credit. Permanent for the
                   session. A retry cannot succeed and must never be made.

WHAT EACH PROVIDER ACTUALLY RETURNS, established from the recorded run and the
providers' documented error shapes:

  OpenAI     SEPARATES THEM CLEANLY. Both are HTTP 429, distinguished by
             ``error.type`` and ``error.code``: ``insufficient_quota`` for
             billing exhaustion, ``rate_limit_exceeded`` for a rate limit.
             The exhaustion message is "You exceeded your current quota,
             please check your plan and billing details".
  Anthropic  SEPARATES THEM BY STATUS. A 429 is ``rate_limit_error`` and is
             always transient. Credit exhaustion is NOT a 429 at all: it is a
             400 ``invalid_request_error`` whose message is "Your credit
             balance is too low to access the Anthropic API".
  Gemini     DOES NOT SEPARATE THEM STRUCTURALLY. Both a per-minute rate limit
             and a daily or billing quota exhaustion return HTTP 429 with
             ``error.status: RESOURCE_EXHAUSTED``. The only discriminator is
             prose in the message, and optionally a ``QuotaFailure`` entry in
             ``error.details``. Stated plainly: this provider cannot be
             classified reliably from its status, so the SAFE DEFAULT APPLIES
             and a Gemini 429 is never retried. It latches only when an
             explicit billing marker is present, because latching on a
             per-minute limit would drop a healthy provider for the session.

THE RECORDED EVIDENCE WAS ITSELF TRUNCATED, which is why the fix starts at the
HTTP seam. ``post_json`` used to raise a plain string truncated at 200
characters, and for both failing providers the distinguishing field sits AFTER
the message, so the classifier never saw it. ``LLMHTTPError`` now carries the
status, the parsed body, and a bounded raw text, and this module reads fields
rather than regex-matching a truncated sentence.

THE LATCH IS PROCESS STATE, NOT PERSISTED STATE. Exhaustion is true of an
account for as long as it stays unfunded, and a restart is the natural moment
to re-check rather than inherit a stale verdict. Keyed by provider LABEL
because the quota belongs to the API key, so every model behind one key is
exhausted together.
"""
from __future__ import annotations

import json
import re
import threading
from datetime import datetime, timezone

# --- Failure kinds -----------------------------------------------------------
# TRANSIENT  retry exactly once inside the existing budget
# EXHAUSTED  never retry, and latch the provider off for the session
# NO_RETRY   never retry, do NOT latch (a certain second failure now, but the
#            provider is not known to be out of credit)
TRANSIENT = "transient"
EXHAUSTED = "exhausted"
NO_RETRY = "no_retry"

# Statuses worth exactly one more attempt when nothing marks exhaustion.
TRANSIENT_STATUS = (408, 409, 425, 429, 500, 502, 503, 504, 529)

# Structured codes that mean the account is out of quota or credit. Read from
# error.type / error.code / error.status, so a message rewording cannot break
# the classification.
EXHAUSTION_CODES = frozenset({
    "insufficient_quota",           # OpenAI billing exhaustion
    "billing_hard_limit_reached",   # OpenAI hard cap
    "credit_balance_too_low",       # Anthropic credit exhaustion
    "quota_exceeded",
})

# Prose markers, the fallback when the body is unparseable or the provider does
# not carry a structured code. Every phrase here is one a provider uses for
# BILLING or QUOTA exhaustion, never for a per-minute rate limit.
EXHAUSTION_TEXT = re.compile(
    r"exceeded your current quota"
    r"|check your (?:plan and )?billing details"
    r"|insufficient[_ ]quota"
    r"|credit balance is too low"
    r"|billing hard limit"
    r"|out of credits?",
    re.IGNORECASE)

# A transport failure that never reached a status line.
TRANSIENT_TEXT = re.compile(
    r"timed out|timeout|connection (?:reset|aborted|error)|temporarily "
    r"unavailable|overloaded|high demand|try again|rate.?limit",
    re.IGNORECASE)

# Providers whose 429 does not structurally separate a rate limit from an
# exhaustion. Their 429 is never retried, per the safe default.
AMBIGUOUS_429_LABELS = frozenset({"gemini"})


def _status_of(exc: Exception) -> int | None:
    """The HTTP status, from the typed field when present, else the message."""
    status = getattr(exc, "status", None)
    if isinstance(status, int):
        return status
    m = re.match(r"HTTP (\d{3})", str(exc))
    return int(m.group(1)) if m else None


def _codes_of(exc: Exception) -> set[str]:
    """Lower-cased type/code/status strings from a parsed provider body."""
    body = getattr(exc, "body", None)
    if not isinstance(body, dict):
        return set()
    out: set[str] = set()
    for scope in (body.get("error"), body):
        if not isinstance(scope, dict):
            continue
        for key in ("type", "code", "status"):
            val = scope.get(key)
            if isinstance(val, str) and val.strip():
                out.add(val.strip().lower())
    return out


def _text_of(exc: Exception) -> str:
    """The fullest error text available.

    The PARSED BODY IS INCLUDED, not just the raw text and the message. Both
    providers that ran dry put the distinguishing sentence in
    ``error.message``, and Anthropic's credit exhaustion carries no structured
    code at all, so a searcher that reads only the exception message misses
    every one of them. Caught by testing against the real error shapes.
    """
    parts = [str(getattr(exc, "text", "") or ""), str(exc)]
    body = getattr(exc, "body", None)
    if isinstance(body, dict):
        try:
            parts.append(json.dumps(body, default=str))
        except Exception:  # noqa: BLE001 - a body is evidence, never a crash
            parts.append(str(body))
    return "\n".join(parts)


def classify(exc: Exception, *, label: str = "") -> str:
    """TRANSIENT, EXHAUSTED, or NO_RETRY for one provider failure.

    ``label`` is the provider LABEL (OpenAI / Anthropic / Gemini). It matters
    only for the ambiguous-429 rule, so a bare exception with no label still
    classifies sensibly and the existing string-only call sites keep working.

    EXHAUSTION IS CHECKED FIRST AND ACROSS EVERY STATUS, because Anthropic
    reports credit exhaustion as a 400 rather than a 429. Keying exhaustion off
    the status code is exactly the mistake this module exists to fix.
    """
    if _codes_of(exc) & EXHAUSTION_CODES or EXHAUSTION_TEXT.search(_text_of(exc)):
        return EXHAUSTED

    status = _status_of(exc)
    if status is None:
        msg = str(exc)
        if msg.startswith("request failed:") or TRANSIENT_TEXT.search(msg):
            return TRANSIENT
        return NO_RETRY

    if status == 429 and str(label).strip().lower() in AMBIGUOUS_429_LABELS:
        # Cannot tell a rate limit from a quota here. Do not retry, and do not
        # latch either: dropping a healthy provider for a per-minute limit
        # costs more than the one retry it saves.
        return NO_RETRY

    return TRANSIENT if status in TRANSIENT_STATUS else NO_RETRY


# --- The session latch -------------------------------------------------------

_lock = threading.Lock()
_exhausted: dict[str, dict] = {}


def mark_exhausted(label: str, *, model_id: str = "", detail: str = "") -> None:
    """Latch a provider off for the rest of the process. Idempotent.

    The FIRST detail wins, because it is the one that diagnosed the condition
    and later calls carry the same cause.
    """
    key = str(label).strip().lower()
    if not key:
        return
    with _lock:
        if key in _exhausted:
            return
        _exhausted[key] = {
            "label": str(label),
            "model_id": str(model_id or ""),
            "detail": str(detail or "")[:300],
            "since": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        }


def is_exhausted(label: str) -> bool:
    with _lock:
        return str(label).strip().lower() in _exhausted


def exhausted_providers() -> dict[str, dict]:
    """Every latched provider, for the startup block, the GUI, and reports."""
    with _lock:
        return {k: dict(v) for k, v in _exhausted.items()}


def exhaustion_line() -> str:
    """One human-readable sentence, empty when nothing is latched.

    Written for the operator surfaces: a council running one-handed because an
    account is dry must be visible, never inferred from a log afterwards.
    """
    latched = exhausted_providers()
    if not latched:
        return ""
    parts = ", ".join(
        f"{v['label']}({v['model_id'] or 'all models'}) since {v['since']}"
        for v in sorted(latched.values(), key=lambda d: d["since"]))
    return (f"PROVIDER EXHAUSTED, not being called: {parts}. "
            "The council is running with fewer providers than configured.")


def reset_exhaustion() -> None:
    """Clear the latch. For tests and for an explicit operator re-check."""
    with _lock:
        _exhausted.clear()
