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
    """True when the cheap Gemini-Flash base-check runs before the council.

    Sourced from ``llm.gate_enabled`` (default True — the gate is on by default).
    """
    return bool((_cfg(cfg_path).get("llm", {}) or {}).get("gate_enabled", True))


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
