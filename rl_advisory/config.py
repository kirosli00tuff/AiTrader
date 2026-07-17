"""Read-only access to the RL-advisory settings in the engine config (Task 4).

Single source of truth = ``config/default_config.yaml`` (overridable via
``MAL_CONFIG_PATH``). Every getter degrades to a safe default when the file,
block, or key is absent, so nothing depends on these being present.

RL SHIPS OFF: ``rl_enabled`` defaults False. The trainer refuses to run until at
least ``rl_min_real_fills`` REAL closed fills exist (no synthetic-data path).
"""
from __future__ import annotations

import os
from functools import lru_cache

# Advisory sizing cap for the RL factor — identical to the dnn_advisory cap so a
# swap of which advisory model serves never changes the ceiling.
RL_ADVISORY_CAP = 0.5

_DEFAULT_MIN_REAL_FILLS = 500


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


def _rl(cfg_path: str | None) -> dict:
    return _cfg(cfg_path).get("rl", {}) or {}


def rl_enabled(cfg_path: str | None = None) -> bool:
    """True only when the operator has explicitly toggled RL on (default False).

    Config ``rl.rl_enabled`` (ships False) is the SHIPPED value, and the
    operator's controls.json ``rl_enabled`` overrides it, the same precedence
    every other GUI-toggleable flag now uses (llm_consensus/control_file.py).

    THIS FLAG ALONE IS NOT THE GATE, and honoring the control file here is only
    safe because of that. CLAUDE.md: "RL ships toggled off, trains only on real
    fills, and activates only past the rl_min_real_fills gate". That gate used to
    live ONLY at the GUI write (api_server.set_rl refuses below it), so a
    hand-edited file of EITHER kind could activate RL under-gated. The gate is
    now enforced at the READ too (rl_advisory.service.rl_gate_unmet), so the hard
    rule is a property of the code rather than of which file someone edited.
    """
    shipped = bool(_rl(cfg_path).get("rl_enabled", False))
    if cfg_path is not None:
        return shipped  # a pinned config ignores the control file (the tests)
    try:
        from llm_consensus import control_file
    except Exception:  # noqa: BLE001
        # rl_advisory must degrade, never raise. service.score_rl promises
        # "none of which ever raise (offline runs must not break)", and this is a
        # CROSS-PACKAGE import: llm_consensus can be absent in a trimmed
        # environment, or half-initialised during a circular import. An
        # unguarded ImportError here propagated through score_rl and would 500
        # the bridge's /score/rl instead of returning a labelled neutral.
        #
        # No control file reachable means no override, so config decides, and
        # config ships RL off. Falling back cannot enable anything.
        return shipped
    return control_file.flag("rl_enabled", shipped)


def rl_min_real_fills(cfg_path: str | None = None) -> int:
    """Real closed fills required before the PPO trainer may run (default 500)."""
    try:
        return int(_rl(cfg_path).get("rl_min_real_fills", _DEFAULT_MIN_REAL_FILLS))
    except (TypeError, ValueError):
        return _DEFAULT_MIN_REAL_FILLS


def crypto_allow_short(cfg_path: str | None = None) -> bool:
    """Whether crypto may go short (from strategy.crypto_allow_short, default False).

    Equities are ALWAYS long-only in paper regardless of this flag; the RL env
    uses this only to decide whether a short action is permitted on crypto.
    """
    strat = _cfg(cfg_path).get("strategy", {}) or {}
    return bool(strat.get("crypto_allow_short", False))
