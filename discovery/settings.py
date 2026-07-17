"""Read-only access to the ``discovery:`` config block.

Mirrors the C++ DiscoveryConfig so the Python funnel and the C++ engine read one
source of truth (config/default_config.yaml, overridable via MAL_CONFIG_PATH).
Every getter degrades to the same safe default the C++ side uses, so a missing
block never enables anything: discovery_enabled and long_term_sleeve_enabled
both default FALSE.

Lists are comma-separated scalars in YAML because the C++ minimal parser has no
sequence support, matching how strategy.whitelist and sleeves.research_whitelist
are already stored.
"""
from __future__ import annotations

from llm_consensus import control_file
from llm_consensus.config_access import config_block

# Defaults mirror config/config.hpp DiscoveryConfig exactly. Change one, change
# both: tests/test_discovery_funnel.py asserts the two stay in parity.
_DEFAULTS: dict[str, object] = {
    "discovery_enabled": False,
    "long_term_sleeve_enabled": False,
    "crypto_active_max": 50,
    "max_finalists": 12,
    "max_survivors": 5,
    "max_council_calls_per_pass": 5,
    "discovery_daily_council_budget": 12,
    "discovery_est_cost_per_call_usd": 0.04,
    "crypto_interval_minutes": 60,
    "equity_interval_minutes": 60,
    "prescreen_min_score": 0.15,
    "stage_a_whale_weight": 0.15,
    "watchlist_max_size": 40,
    "watchlist_stale_hours": 48,
}


def _block(cfg_path: str | None) -> dict:
    """Config, with the operator's control file layered over it.

    Precedence: controls.json wins when it carries a key, else config. That is
    the same precedence feed_mode and clock_mode use, so a missing control file
    never turns anything on: config ships both discovery flags false.

    An explicit cfg_path means a caller is pinning a config (the tests), so the
    control file is ignored. Otherwise a developer's local controls.json would
    leak into a test that thought it had set everything.
    """
    return control_file.overlay(config_block("discovery", cfg_path),
                                "discovery", cfg_path)


def _num(key: str, cfg_path: str | None):
    default = _DEFAULTS[key]
    try:
        return type(default)(_block(cfg_path).get(key, default))
    except (TypeError, ValueError):
        return default


def _csv(key: str, cfg_path: str | None) -> list[str]:
    raw = _block(cfg_path).get(key, "")
    if isinstance(raw, list):  # tolerate a real YAML sequence if hand-edited
        return [str(s).strip() for s in raw if str(s).strip()]
    return [s.strip() for s in str(raw or "").split(",") if s.strip()]


# --- Flags (both default FALSE: nothing here runs until an operator opts in) --

def discovery_enabled(cfg_path: str | None = None) -> bool:
    """True when the hourly discovery funnel runs. OFF by default."""
    return bool(_block(cfg_path).get("discovery_enabled", False))


def long_term_sleeve_enabled(cfg_path: str | None = None) -> bool:
    """True when the research_satellite long-term strategy runs. OFF by default.

    Distinct from sleeves.research_satellite_enabled: that turns the SLEEVE on,
    this turns the long-term quality-and-catalyst STRATEGY on within it. Both
    must be true for a long-term position to open.
    """
    return bool(_block(cfg_path).get("long_term_sleeve_enabled", False))


# --- Universe ---------------------------------------------------------------

def crypto_universe(cfg_path: str | None = None) -> list[str]:
    """The broader crypto list the daily refresh selects the active set from."""
    return _csv("crypto_universe", cfg_path)


def equity_universe(cfg_path: str | None = None) -> list[str]:
    """The stable curated equity list. Liquid names only."""
    return _csv("equity_universe", cfg_path)


def crypto_active_max(cfg_path: str | None = None) -> int:
    """How many crypto instruments stay active after the daily refresh."""
    return int(_num("crypto_active_max", cfg_path))


# --- Funnel ceilings (hard cost bounds, per stage) ---------------------------

def max_finalists(cfg_path: str | None = None) -> int:
    """Stage A output ceiling (default 12, inside the 10-15 band)."""
    return int(_num("max_finalists", cfg_path))


def max_survivors(cfg_path: str | None = None) -> int:
    """Stage B output ceiling (default 5, inside the 3-6 band)."""
    return int(_num("max_survivors", cfg_path))


def max_council_calls_per_pass(cfg_path: str | None = None) -> int:
    """Hard ceiling on full-council calls in one discovery pass."""
    return int(_num("max_council_calls_per_pass", cfg_path))


def discovery_daily_council_budget(cfg_path: str | None = None) -> int:
    """Daily discovery council budget. SEPARATE from and ADDITIVE to the trading
    council budget, so discovery can never eat the quant loop's calls."""
    return int(_num("discovery_daily_council_budget", cfg_path))


def discovery_est_cost_per_call_usd(cfg_path: str | None = None) -> float:
    return float(_num("discovery_est_cost_per_call_usd", cfg_path))


def crypto_interval_minutes(cfg_path: str | None = None) -> int:
    return int(_num("crypto_interval_minutes", cfg_path))


def equity_interval_minutes(cfg_path: str | None = None) -> int:
    return int(_num("equity_interval_minutes", cfg_path))


def prescreen_min_score(cfg_path: str | None = None) -> float:
    """Stage A floor: below this an instrument is dropped as low-signal."""
    return float(_num("prescreen_min_score", cfg_path))


def stage_a_whale_weight(cfg_path: str | None = None) -> float:
    """Weight of whale activity in the Stage-A pre-screen rank.

    Operator-tunable without touching code. The five fixed components sum to 1.0
    (momentum 0.30, volatility 0.25, gap 0.15, sentiment 0.15, native 0.15), and
    this adds on top before normalization. At the default 0.15 whale is one sixth
    of the total: level with sentiment and native, below momentum and volatility,
    so it can lift a name into the finalist set but can never dominate the
    pre-screen on its own. Set 0.0 to turn surfacing off entirely, which restores
    the exact pre-whale ranking. This is a SURFACING weight only: the Stage-C
    Level-4 whale evaluation keeps its own 0.35 cap, untouched.
    """
    return float(_num("stage_a_whale_weight", cfg_path))


def watchlist_max_size(cfg_path: str | None = None) -> int:
    return int(_num("watchlist_max_size", cfg_path))


def watchlist_stale_hours(cfg_path: str | None = None) -> int:
    """A watchlist entry not re-confirmed by a pass within this many hours is
    pruned as stale."""
    return int(_num("watchlist_stale_hours", cfg_path))
