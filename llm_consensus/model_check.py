"""Startup model-reachability validation (non-fatal).

Fetches each provider's live model list and warns when a configured council
model is not reachable with the current key. This turns a silent mid-trade 404
into a visible startup warning.

Non-fatal by design: an absent key, an unreachable provider, or a failed list
call warns-or-skips and NEVER raises, so a provider outage can never block the
engine or the bridge from starting. A key value is never logged or returned.

ADVISORY-ONLY surface: this touches no risk logic, no gate, and no execution.
"""
from __future__ import annotations

import json
import logging
import os
import re
import urllib.error
import urllib.request

log = logging.getLogger("llm_consensus")

_TIMEOUT = 8.0

# ensemble slot -> (provider label, env var). llm_gate shares the Anthropic key.
_SLOT_PROVIDER: dict[str, tuple[str, str]] = {
    "llm_primary": ("openai", "OPENAI_API_KEY"),
    "llm_secondary": ("anthropic", "ANTHROPIC_API_KEY"),
    "llm_tertiary": ("gemini", "GEMINI_API_KEY"),
    "llm_gate": ("anthropic", "ANTHROPIC_API_KEY"),
}

# A configured id counts as reachable if it is an exact list member OR a
# date-suffixed alias of one (e.g. claude-haiku-4-5 -> claude-haiku-4-5-20251001,
# which the provider resolves server-side). A word suffix like "-preview" is NOT
# a date alias, so gemini-3.1-pro does NOT falsely match gemini-3.1-pro-preview.
_DATE_ALIAS = r"-\d{6,}$"


def _resolve(env: str) -> str | None:
    """Keystore-first key resolution, degrading to env, never logged."""
    try:
        from account_manager.credentials import resolve_env
        val = resolve_env(env)
        if val:
            return val
    except Exception:
        pass
    return os.environ.get(env) or None


def _get_json(url: str, headers: dict) -> dict:
    req = urllib.request.Request(url, headers=headers, method="GET")
    with urllib.request.urlopen(req, timeout=_TIMEOUT) as r:  # noqa: S310
        return json.loads(r.read().decode("utf-8", "replace"))


def list_models(provider: str, key: str) -> set[str] | None:
    """Reachable model ids for a provider, or None when the list is unavailable.

    For Gemini only models that support ``generateContent`` are returned, since
    a chat/council call needs that method.
    """
    try:
        if provider == "openai":
            data = _get_json("https://api.openai.com/v1/models",
                             {"Authorization": f"Bearer {key}"})
            return {str(m.get("id", "")) for m in data.get("data", [])}
        if provider == "anthropic":
            data = _get_json("https://api.anthropic.com/v1/models?limit=100",
                             {"x-api-key": key,
                              "anthropic-version": "2023-06-01"})
            return {str(m.get("id", "")) for m in data.get("data", [])}
        if provider == "gemini":
            data = _get_json(
                "https://generativelanguage.googleapis.com/v1beta/models"
                "?pageSize=200", {"x-goog-api-key": key})
            out: set[str] = set()
            for m in data.get("models", []):
                methods = m.get("supportedGenerationMethods") or []
                if "generateContent" in methods:
                    out.add(str(m.get("name", "")).removeprefix("models/"))
            return out
    except Exception as e:  # network / status / decode -> unavailable, never raise
        log.debug("model list unavailable for %s: %s", provider, e)
        return None
    return None


def _reachable(model: str, ids: set[str]) -> bool:
    if model in ids:
        return True
    alias = re.compile(re.escape(model) + _DATE_ALIAS)
    return any(alias.match(i) for i in ids)


def validate_configured_models(cfg_path: str | None = None) -> list[dict]:
    """Check each configured council model against the provider live list.

    Returns one record per configured slot with a ``status`` of:
      * ``ok``        - the model is reachable with the current key.
      * ``warning``   - the list was fetched and the model is NOT in it.
      * ``unchecked`` - no key, or the list could not be fetched (no false alarm).
    A key value never appears in any record.
    """
    from .config_access import llm_model_names
    names = llm_model_names(cfg_path)
    lists: dict[str, set[str] | None] = {}   # provider -> ids (fetched once)
    keys: dict[str, str | None] = {}         # provider -> resolved key
    out: list[dict] = []
    for slot, (provider, env) in _SLOT_PROVIDER.items():
        model = names.get(slot)
        if not model:
            continue
        if provider not in keys:
            keys[provider] = _resolve(env)
        key = keys[provider]
        if not key:
            out.append({"slot": slot, "provider": provider, "model": model,
                        "status": "unchecked", "detail": f"{env} not set"})
            continue
        if provider not in lists:
            lists[provider] = list_models(provider, key)
        ids = lists[provider]
        if ids is None:
            out.append({"slot": slot, "provider": provider, "model": model,
                        "status": "unchecked", "detail": "model list unavailable"})
        elif _reachable(model, ids):
            out.append({"slot": slot, "provider": provider, "model": model,
                        "status": "ok", "detail": "reachable"})
        else:
            out.append({"slot": slot, "provider": provider, "model": model,
                        "status": "warning",
                        "detail": f"not in the {provider} live model list"})
    return out


def warn_unreachable_models(cfg_path: str | None = None, printer=None) -> list[str]:
    """Emit one warning per unreachable configured model. Never raises.

    Logs each warning and, when ``printer`` is given (e.g. the bridge's
    ``safe_print``), prints it so it is visible at startup. Returns the warning
    strings (empty when every configured model is ok or unchecked).
    """
    warnings: list[str] = []
    try:
        for r in validate_configured_models(cfg_path):
            if r["status"] == "warning":
                warnings.append(
                    f"configured model '{r['model']}' ({r['slot']}, "
                    f"{r['provider']}) is NOT reachable: {r['detail']}. "
                    f"Council calls to it will fail. Update llm_models in config.")
    except Exception as e:  # defence-in-depth: validation must never block startup
        log.debug("model validation skipped: %s", e)
        return []
    for w in warnings:
        log.warning(w)
        if printer is not None:
            printer(f"  WARNING: {w}")
    return warnings
