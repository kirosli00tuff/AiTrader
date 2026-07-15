"""Read-only access to the LLM-council settings in the engine config.

Single source of truth = ``config/default_config.yaml`` (overridable via
``MAL_CONFIG_PATH``). Every getter degrades gracefully to a safe default when
the file, block, or key is absent, so the offline paper loop never depends on
these being present.
"""
from __future__ import annotations

import os
from functools import lru_cache


def _default_config_path() -> str:
    return os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        "config", "default_config.yaml")


def _config_path(cfg_path: str | None) -> str:
    return cfg_path or os.environ.get("MAL_CONFIG_PATH") or _default_config_path()


@lru_cache(maxsize=8)
def _load(path: str) -> dict:
    try:
        import yaml
        with open(path) as fh:
            return yaml.safe_load(fh) or {}
    except Exception:
        return {}


def _cfg(cfg_path: str | None) -> dict:
    return _load(_config_path(cfg_path))


def llm_model_names(cfg_path: str | None = None) -> dict[str, str]:
    """Concrete model id per ensemble slot from the ``llm_models`` block."""
    names = _cfg(cfg_path).get("llm_models", {}) or {}
    return {str(k): str(v) for k, v in names.items()}


def use_real_council(cfg_path: str | None = None) -> bool:
    """True when the real multi-provider council should score llm_ factors.

    Sourced from ``llm.use_real_council`` (default False). The engine only
    actually swaps in the real council when this is True *and* it is launched
    with ``--bridge`` (see ``core/main.cpp`` / ``python_bridge``).
    """
    return bool((_cfg(cfg_path).get("llm", {}) or {}).get("use_real_council", False))


def gate_enabled(cfg_path: str | None = None) -> bool:
    """True when the cheap Claude Haiku base-check runs before the council.

    Sourced from ``llm.gate_enabled`` (default True — the gate is on by default).
    """
    return bool((_cfg(cfg_path).get("llm", {}) or {}).get("gate_enabled", True))


def equities_market_hours_only(cfg_path: str | None = None) -> bool:
    """True when US equities skip the council outside regular trading hours.

    Sourced from ``engine.equities_market_hours_only`` (default True). Council
    cost cut (Task 5): equity symbols (SPY, QQQ) skip the base-check gate + council
    outside US RTH; crypto trades 24/7 and is never skipped for market hours.
    """
    return bool((_cfg(cfg_path).get("engine", {}) or {}).get(
        "equities_market_hours_only", True))


# Ensemble slot -> default weight (matches config model_weights defaults).
_DEFAULT_SLOT_WEIGHTS: dict[str, float] = {
    "llm_primary": 0.27,
    "llm_secondary": 0.18,
    "llm_tertiary": 0.12,
}


def slot_weight(slot: str, cfg_path: str | None = None) -> float:
    """Ensemble weight for a slot, from ``model_weights.<slot>_weight``."""
    mw = _cfg(cfg_path).get("model_weights", {}) or {}
    default = _DEFAULT_SLOT_WEIGHTS.get(slot, 0.2)
    try:
        return float(mw.get(f"{slot}_weight", default))
    except (TypeError, ValueError):
        return default


# --- Council cost controls (Task 4) -----------------------------------------
# Mirrors the C++ ``council:`` config block. The engine owns budget/cooldown/
# neutral-skip enforcement; the Python side uses ``council_max_tokens`` to cap
# every provider response so a full council call stays cheap.
_COUNCIL_DEFAULTS: dict[str, float] = {
    "council_daily_budget": 30,
    "per_symbol_council_cooldown_minutes": 60,
    "council_max_tokens": 2048,
    "council_min_confidence": 0.6,
    "council_min_agreement": 2,
    "neutral_skip_strength_threshold": 0.5,
    # Bridge-to-provider call timeouts (seconds). Mirror the C++ council block.
    # A single slow or hung provider fails alone after provider_timeout_seconds,
    # the council proceeds on the rest. The gate has its own shorter budget.
    "provider_timeout_seconds": 30,
    "gate_timeout_seconds": 15,
}


def _council(cfg_path: str | None) -> dict:
    return _cfg(cfg_path).get("council", {}) or {}


def profile(cfg_path: str | None = None) -> str:
    """Active strategy profile: swing (default) or active_quant. Mirrors the C++
    strategy.profile. When active_quant, the active_quant block overlays the
    council cost controls (budget, cooldown, spend ceiling, tier thresholds)."""
    return str((_cfg(cfg_path).get("strategy", {}) or {}).get("profile", "swing"))


def _active_quant(cfg_path: str | None) -> dict:
    return _cfg(cfg_path).get("active_quant", {}) or {}


def _council_num(key: str, cfg_path: str | None):
    default = _COUNCIL_DEFAULTS[key]
    src = _council(cfg_path)
    # active_quant overlays the council block, matching the C++ loader.
    if profile(cfg_path) == "active_quant" and key in _active_quant(cfg_path):
        src = _active_quant(cfg_path)
    try:
        return type(default)(src.get(key, default))
    except (TypeError, ValueError):
        return default


# Cost controls (Task 9). A rough per-call cost estimate times the running
# council-call counts, checked against a daily and a monthly ceiling. 0.0 = off.
# The C++ engine owns real enforcement; this mirror lets the Python cost/UI side
# reason about the ceiling. Swing leaves the ceilings 0.0 (disabled).
_SPEND_DEFAULTS: dict[str, float] = {
    "council_est_cost_per_call_usd": 0.04,
    "council_daily_spend_ceiling_usd": 0.0,
    "council_monthly_spend_ceiling_usd": 0.0,
    "fast_tier_max_notional_pct": 0.0,
    "fast_tier_max_conviction": 0.0,
}


def _spend_num(key: str, cfg_path: str | None) -> float:
    default = _SPEND_DEFAULTS[key]
    src = _council(cfg_path)
    if profile(cfg_path) == "active_quant" and key in _active_quant(cfg_path):
        src = _active_quant(cfg_path)
    try:
        return float(src.get(key, default))
    except (TypeError, ValueError):
        return default


def council_est_cost_per_call_usd(cfg_path: str | None = None) -> float:
    """Estimated cost of one full council call (gate + three providers)."""
    return _spend_num("council_est_cost_per_call_usd", cfg_path)


def council_daily_spend_ceiling_usd(cfg_path: str | None = None) -> float:
    """Daily council spend ceiling in USD (0.0 = disabled)."""
    return _spend_num("council_daily_spend_ceiling_usd", cfg_path)


def council_monthly_spend_ceiling_usd(cfg_path: str | None = None) -> float:
    """Monthly council spend ceiling in USD (0.0 = disabled)."""
    return _spend_num("council_monthly_spend_ceiling_usd", cfg_path)


def fast_tier_max_notional_pct(cfg_path: str | None = None) -> float:
    """Fast-tier notional threshold as a fraction of equity (0.0 = never fast)."""
    return _spend_num("fast_tier_max_notional_pct", cfg_path)


def fast_tier_max_conviction(cfg_path: str | None = None) -> float:
    """Fast-tier native conviction threshold (0.0 = never fast)."""
    return _spend_num("fast_tier_max_conviction", cfg_path)


# --- Core-satellite sleeves (research_satellite cost control) ---------------
# Mirrors the C++ sleeves: block. The engine owns real enforcement; these let the
# Python research path and the GUI reason about the budget and combined ceiling.
_SLEEVE_DEFAULTS: dict[str, float] = {
    "research_conviction_threshold": 0.70,
    "research_daily_budget": 6,
    "research_est_cost_per_call_usd": 0.08,
    "combined_monthly_spend_ceiling_usd": 100.0,
}


def _sleeves(cfg_path: str | None) -> dict:
    return _cfg(cfg_path).get("sleeves", {}) or {}


def _sleeve_num(key: str, cfg_path: str | None):
    default = _SLEEVE_DEFAULTS[key]
    try:
        return type(default)(_sleeves(cfg_path).get(key, default))
    except (TypeError, ValueError):
        return default


def research_satellite_enabled(cfg_path: str | None = None) -> bool:
    """True when the research_satellite sleeve is on (OFF by default)."""
    return bool(_sleeves(cfg_path).get("research_satellite_enabled", False))


def research_conviction_threshold(cfg_path: str | None = None) -> float:
    """Min council conviction to open a satellite position."""
    return float(_sleeve_num("research_conviction_threshold", cfg_path))


def research_daily_budget(cfg_path: str | None = None) -> int:
    """Max deep-research council calls per day."""
    return int(_sleeve_num("research_daily_budget", cfg_path))


def research_est_cost_per_call_usd(cfg_path: str | None = None) -> float:
    """Estimated cost of one deep-research council call."""
    return float(_sleeve_num("research_est_cost_per_call_usd", cfg_path))


def combined_monthly_spend_ceiling_usd(cfg_path: str | None = None) -> float:
    """Combined (quant council + research) monthly spend ceiling (0 = off)."""
    return float(_sleeve_num("combined_monthly_spend_ceiling_usd", cfg_path))


def combined_spend_ceiling_reached(council_calls_month: int,
                                   research_calls_month: int,
                                   cfg_path: str | None = None) -> bool:
    """True when combined council + research spend reaches the monthly ceiling,
    which pauses new council AND research calls in BOTH sleeves. Mirrors the C++
    Engine::combined_spend_ceiling_reached."""
    ceiling = combined_monthly_spend_ceiling_usd(cfg_path)
    if ceiling <= 0.0:
        return False
    council = council_calls_month * council_est_cost_per_call_usd(cfg_path)
    research = research_calls_month * research_est_cost_per_call_usd(cfg_path)
    return council + research >= ceiling


def spend_ceiling_reached(calls_today: int, calls_month: int,
                          cfg_path: str | None = None) -> bool:
    """True when estimated council spend has reached a daily or monthly ceiling.
    Mirrors signal_engine::spend_ceiling_reached. When true the engine forces the
    fast tier (skips the council)."""
    est = council_est_cost_per_call_usd(cfg_path)
    if est <= 0.0:
        return False
    daily = council_daily_spend_ceiling_usd(cfg_path)
    monthly = council_monthly_spend_ceiling_usd(cfg_path)
    if daily > 0.0 and calls_today * est >= daily:
        return True
    if monthly > 0.0 and calls_month * est >= monthly:
        return True
    return False


def council_max_tokens(cfg_path: str | None = None) -> int:
    """Per-provider response token cap for a full council call (default 400)."""
    return int(_council_num("council_max_tokens", cfg_path))


def council_daily_budget(cfg_path: str | None = None) -> int:
    """Max full-council calls per day (default 30)."""
    return int(_council_num("council_daily_budget", cfg_path))


def per_symbol_council_cooldown_minutes(cfg_path: str | None = None) -> int:
    """Minutes between full-council calls for the same symbol (default 60)."""
    return int(_council_num("per_symbol_council_cooldown_minutes", cfg_path))


def council_min_confidence(cfg_path: str | None = None) -> float:
    """Council-side confidence threshold (separate from the Layer-1 gate)."""
    return float(_council_num("council_min_confidence", cfg_path))


def council_min_agreement(cfg_path: str | None = None) -> int:
    """Council-side minimum provider agreement (separate from the gate)."""
    return int(_council_num("council_min_agreement", cfg_path))


def neutral_skip_strength_threshold(cfg_path: str | None = None) -> float:
    """Skip the council when regime is neutral and strength is below this."""
    return float(_council_num("neutral_skip_strength_threshold", cfg_path))


def provider_timeout_seconds(cfg_path: str | None = None) -> float:
    """Per real-provider call timeout (default 30s). A slow or hung provider
    fails alone after this; the council proceeds on the providers that answered."""
    return float(_council_num("provider_timeout_seconds", cfg_path))


def gate_timeout_seconds(cfg_path: str | None = None) -> float:
    """Haiku base-check gate call timeout (default 15s). On timeout the gate
    proceeds (fail-open to the council) rather than dropping the candidate."""
    return float(_council_num("gate_timeout_seconds", cfg_path))
