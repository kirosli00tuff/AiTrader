"""Live provider cost signal (GET /providers/cost).

Per provider we report, in priority order: provider-reported remaining balance
where a provider exposes it, provider-reported spend where it exposes that, and
a LOCAL ESTIMATED day and month spend always. No provider exposes a stable
public prepaid-balance endpoint for a plain API key, so balance and spend stay
null today and the reported signal is the local estimate, clearly labeled. The
estimate is computed from the council calls actually recorded in model_outputs
times the per-model token prices in config/provider_prices.yaml, so prices
update without a code change.

SAFETY. Read-only. Never logs or returns a key value. Reads run concurrently
with a timeout, and a failed read never breaks the panel (it falls back to the
local estimate). Absent key reports status unavailable, present key reports
estimated (no live balance endpoint), a real balance read would report live.
"""
from __future__ import annotations

import os
from concurrent.futures import ThreadPoolExecutor, as_completed

import yaml

from api_server import store

_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# slot (model_outputs.model) -> (provider label, key env var)
SLOTS = [
    ("llm_primary", "OpenAI", "OPENAI_API_KEY"),
    ("llm_secondary", "Anthropic", "ANTHROPIC_API_KEY"),
    ("llm_tertiary", "Google", "GEMINI_API_KEY"),
]


def _prices_path() -> str:
    return os.environ.get("MAL_PROVIDER_PRICES_PATH",
                          os.path.join(_REPO, "config", "provider_prices.yaml"))


def _prices() -> dict:
    try:
        with open(_prices_path()) as fh:
            return yaml.safe_load(fh) or {}
    except Exception:
        return {}


def _model_for_slot(slot: str) -> str:
    return store.llm_models().get(slot, "")


def _key_present(env: str) -> bool:
    try:
        from account_manager.credentials import resolve_env
        return bool(resolve_env(env))
    except Exception:
        return bool(os.environ.get(env))


def _calls(slot: str, period: str) -> int:
    key = store._now()[:10] if period == "day" else store._now()[:7]
    row = store.query_one(
        "SELECT COUNT(*) AS n FROM model_outputs "
        "WHERE model = ? AND substr(ts,1,?) = ?", (slot, len(key), key))
    return int(row["n"]) if row and row.get("n") is not None else 0


def _per_call_cost(model: str, pr: dict) -> float:
    mp = (pr.get("models", {}) or {}).get(model, {}) or {}
    ein = float(pr.get("est_input_tokens", 900))
    eout = float(pr.get("est_output_tokens", 400))
    return ein / 1e6 * float(mp.get("input", 0.0)) + eout / 1e6 * float(mp.get("output", 0.0))


def _one(slot: str, provider: str, env: str) -> dict:
    pr = _prices()
    model = _model_for_slot(slot)
    cd, cm = _calls(slot, "day"), _calls(slot, "month")
    pcc = _per_call_cost(model, pr)
    present = _key_present(env)
    # No stable public balance endpoint for a plain key -> local estimate.
    status = "estimated" if present else "unavailable"
    return {"provider": provider, "model": model, "balance": None, "spend": None,
            "estimated_day": round(cd * pcc, 4), "estimated_month": round(cm * pcc, 4),
            "calls_today": cd, "calls_month": cm,
            "status": status, "source": "local_estimate"}


def _fallback(slot: str, provider: str) -> dict:
    return {"provider": provider, "model": _model_for_slot(slot), "balance": None,
            "spend": None, "estimated_day": 0.0, "estimated_month": 0.0,
            "calls_today": 0, "calls_month": 0, "status": "unavailable",
            "source": "local_estimate"}


def provider_cost() -> dict:
    results: dict[str, dict] = {}
    with ThreadPoolExecutor(max_workers=len(SLOTS)) as ex:
        futs = {ex.submit(_one, slot, prov, env): prov for slot, prov, env in SLOTS}
        try:
            for f in as_completed(futs, timeout=8):
                r = f.result()
                results[r["provider"]] = r
        except Exception:
            pass
    ordered = [results.get(prov) or _fallback(slot, prov) for slot, prov, _e in SLOTS]
    return {"providers": ordered, "currency": "USD",
            "totals": {"estimated_day": round(sum(p["estimated_day"] for p in ordered), 4),
                       "estimated_month": round(sum(p["estimated_month"] for p in ordered), 4)},
            "ts": store._now()}


def estimated_day_total() -> float:
    return provider_cost()["totals"]["estimated_day"]
