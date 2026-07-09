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
    "council_max_tokens": 400,
    "council_min_confidence": 0.6,
    "council_min_agreement": 2,
    "neutral_skip_strength_threshold": 0.5,
}


def _council(cfg_path: str | None) -> dict:
    return _cfg(cfg_path).get("council", {}) or {}


def _council_num(key: str, cfg_path: str | None):
    default = _COUNCIL_DEFAULTS[key]
    try:
        return type(default)(_council(cfg_path).get(key, default))
    except (TypeError, ValueError):
        return default


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
