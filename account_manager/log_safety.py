"""Credential-shaped-string masking for log output (Task 9 security hardening).

Any string headed for stdout/stderr may accidentally carry a secret (an API key
echoed inside an error message, a URL with an embedded token, a PEM block). This
module redacts credential-shaped substrings *before* they are printed, so the
bridge and services never leak a live secret into logs, terminals, or files.

This complements ``account_manager.credentials._mask`` (which fully masks a
*known* secret value by name) by scanning *arbitrary* text for anything that
merely looks like a secret. It is intentionally conservative: it only redacts
well-known credential shapes and explicit ``key=value`` assignments so it does
not mangle ordinary log lines.
"""
from __future__ import annotations

import re

_REDACTED = "***REDACTED***"

# Order matters: more specific prefixes (sk-ant-) are covered by the general
# sk- rule, so a single pass is fine. Each pattern targets a credential shape.
_SECRET_PATTERNS: tuple[re.Pattern[str], ...] = (
    # OpenAI / Anthropic style keys: sk-... and sk-ant-... (>= 12 body chars).
    re.compile(r"sk-(?:ant-)?[A-Za-z0-9_-]{12,}"),
    # AWS access key IDs.
    re.compile(r"AKIA[0-9A-Z]{16}"),
    # GitHub tokens (classic + fine-grained).
    re.compile(r"gh[pousr]_[A-Za-z0-9]{20,}"),
    re.compile(r"github_pat_[A-Za-z0-9_]{20,}"),
    # Google API keys.
    re.compile(r"AIza[0-9A-Za-z_-]{20,}"),
    # Slack tokens.
    re.compile(r"xox[baprs]-[A-Za-z0-9-]{10,}"),
    # HTTP bearer / authorization header values.
    re.compile(r"(?i)\bBearer\s+[A-Za-z0-9._~+/-]{12,}=*"),
    # PEM private-key blocks (any single-line remnant of one).
    re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----.*?-----END [A-Z ]*PRIVATE KEY-----",
               re.DOTALL),
    # Explicit secret-ish assignments: api_key=..., token: "...", secret=...
    re.compile(r"(?i)\b(?:api[_-]?key|secret|token|password|passwd|pwd)\b"
               r"\s*[:=]\s*['\"]?[A-Za-z0-9._~+/-]{6,}['\"]?"),
)


def mask_secrets(text: str) -> str:
    """Return ``text`` with any credential-shaped substrings redacted.

    Safe to call on any log line; ordinary text is returned unchanged.
    """
    if not text:
        return text
    out = text
    for pat in _SECRET_PATTERNS:
        out = pat.sub(_REDACTED, out)
    return out


def safe_print(*args: object, **kwargs: object) -> None:
    """``print`` with every argument passed through :func:`mask_secrets`.

    Use in place of ``print`` for any operational log line so a stray secret is
    never emitted to stdout/stderr.
    """
    masked = [mask_secrets(str(a)) for a in args]
    print(*masked, **kwargs)  # type: ignore[arg-type]
