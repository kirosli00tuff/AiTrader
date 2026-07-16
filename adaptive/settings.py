"""Read-only access to the ``adaptive_realtime:`` config block.

Mirrors the C++ AdaptiveRealtimeConfig so the Python adaptive layer and the C++
engine read one source of truth (config/default_config.yaml, overridable via
MAL_CONFIG_PATH), with the operator's controls.json layered over it. Same shape
and same precedence as discovery/settings.py, deliberately: two layers that both
ship disabled should be turned on the same way.

NAMING. The block is ``adaptive_realtime``, not ``adaptive``, because
``adaptive:`` is already taken by the LEARNING tuner
(adaptive.rule_based_weight_floor and friends). Two unrelated things called
"adaptive" is a wart, but silently colliding with the tuner's block would be
worse. The tuner tunes weights from closed-trade PnL. This layer reads news. They
share a word, nothing else.

All three flags default FALSE. A missing block, a missing file, a malformed file,
and a fresh checkout all mean the same thing: nothing here runs.
"""
from __future__ import annotations

import json
import os

from llm_consensus.config_access import config_block

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

_BLOCK = "adaptive_realtime"

# Defaults mirror config/config.hpp AdaptiveRealtimeConfig exactly. Change one,
# change both: tests/test_adaptive_settings.py asserts the two stay in parity.
_DEFAULTS: dict[str, object] = {
    # The three flags. All FALSE. See CONTEXT.md for why there is no fourth.
    "adaptive_news_feed_enabled": False,
    "adaptive_watchlist_shaping_enabled": False,
    "adaptive_react_defensive_enabled": False,
    # Feed (Task 1)
    "poll_interval_seconds": 60,
    "max_symbols_per_poll": 25,
    "news_lookback_minutes": 15,
    "general_news_enabled": True,
    # Materiality (Task 2). The free filter. Tuned so the vast majority of a
    # normal news day is dropped without a token spent.
    "materiality_min_sentiment": 0.55,
    "materiality_keywords": (
        "bankruptcy,fraud,investigation,sec probe,delisting,halt,halted,"
        "recall,lawsuit,default,downgrade,guidance cut,profit warning,"
        "resignation,ceo steps down,restatement,short seller,hack,breach,"
        "acquisition,merger,buyout,takeover,earnings beat,earnings miss,"
        "fda approval,clinical trial,bankrupt,liquidation,margin call"),
    # Interpretation (Task 3). A dedicated budget, separate from and additive to
    # the discovery and trading budgets. Escalation only.
    "adaptive_daily_llm_budget": 20,
    "adaptive_est_cost_per_call_usd": 0.02,
    "max_interpretations_per_poll": 3,
    "interpretation_model": "claude-haiku-4-5",
    "interpretation_min_relevance": 0.40,
    # Action (Task 5)
    "action_min_severity": 0.60,
    "action_max_age_seconds": 300,
    "defensive_trim_fraction": 0.50,
}


def _control_dir() -> str:
    """Where the operator control files live. Mirrors the engine and the API:
    env MAL_CONTROL_DIR, else config system.control_dir, else .control."""
    env = os.environ.get("MAL_CONTROL_DIR")
    if env:
        return env
    sys_cfg = config_block("system", None)
    return sys_cfg.get("control_dir") or os.path.join(_REPO_ROOT, ".control")


def _controls() -> dict:
    """The adaptive_realtime block of controls.json, {} when absent or malformed.

    Read fresh every call, NOT cached: the poller is a separate process from the
    GUI, so a cached value would keep polling and keep spending after the
    operator turned it off. A missing or broken file means "no override", which
    falls back to config, which ships all three flags false.
    """
    try:
        with open(os.path.join(_control_dir(), "controls.json")) as fh:
            d = json.load(fh).get(_BLOCK)
        return d if isinstance(d, dict) else {}
    except Exception:  # noqa: BLE001 - a control file is never load-bearing
        return {}


def _block(cfg_path: str | None) -> dict:
    """Config, with the operator's control file layered over it.

    An explicit cfg_path means a caller is pinning a config (the tests), so the
    control file is ignored. Otherwise a developer's local controls.json would
    leak into a test that thought it had set everything.
    """
    cfg = config_block(_BLOCK, cfg_path)
    if cfg_path is not None:
        return cfg
    return {**cfg, **_controls()}


def _num(key: str, cfg_path: str | None):
    default = _DEFAULTS[key]
    try:
        return type(default)(_block(cfg_path).get(key, default))
    except (TypeError, ValueError):
        return default


# --- Flags (all three default FALSE) ----------------------------------------

def news_feed_enabled(cfg_path: str | None = None) -> bool:
    """True when the Finnhub event poller runs. OFF by default.

    This is the master flag for the OBSERVE half. With it off, no poll happens,
    no event is stored, and no Finnhub call is made by this layer.
    """
    return bool(_block(cfg_path).get("adaptive_news_feed_enabled", False))


def watchlist_shaping_enabled(cfg_path: str | None = None) -> bool:
    """True when the layer may add funnel referrals and prune the watchlist.

    The SAFE half, enableable on its own: shaping changes what is looked at, not
    what is held. discovery/watchlist.py consults this directly, so the reserved
    ``adaptive_react`` source stays refused until it is on.
    """
    return bool(
        _block(cfg_path).get("adaptive_watchlist_shaping_enabled", False))


def react_defensive_enabled(cfg_path: str | None = None) -> bool:
    """True when a defensive action may be queued for the engine. OFF by default.

    The REACT half, and the only flag that lets a live event change a POSITION.
    It can only ever reduce or freeze one. There is deliberately no counterpart
    flag for aggressive actions: see adaptive/actions.py.
    """
    return bool(_block(cfg_path).get("adaptive_react_defensive_enabled", False))


def any_enabled(cfg_path: str | None = None) -> bool:
    """True when any part of the layer is on. The startup block prints this."""
    return (news_feed_enabled(cfg_path) or watchlist_shaping_enabled(cfg_path)
            or react_defensive_enabled(cfg_path))


# --- Feed -------------------------------------------------------------------

def poll_interval_seconds(cfg_path: str | None = None) -> int:
    """How often the poller wakes. Once a minute by default.

    A poll costs up to 2 * max_symbols_per_poll + 1 Finnhub calls when the
    sentiment cache is cold, so the free tier's 60/min is what bounds the symbol
    count, not this interval. See max_symbols_per_poll.
    """
    return int(_num("poll_interval_seconds", cfg_path))


def max_symbols_per_poll(cfg_path: str | None = None) -> int:
    """Hard ceiling on symbols queried per poll. Bounds the call rate no matter
    how large the watchlist grows.

    THE ARITHMETIC MATTERS. Each symbol costs a company_news call AND (on a cold
    sentiment cache) a news_sentiment call, plus one general_news call for the
    poll: 2N + 1. Against the free tier's 60 calls/minute that caps N at 29. The
    default 25 leaves 51 calls, i.e. real headroom. The API clamps this to 29 for
    the same reason. Raising it past that does not fail loudly; it makes the
    poller stall on its own rate limiter.
    """
    return int(_num("max_symbols_per_poll", cfg_path))


def news_lookback_minutes(cfg_path: str | None = None) -> int:
    """How far back each poll looks. Wider than the interval on purpose, so a
    slow or skipped poll does not silently lose events."""
    return int(_num("news_lookback_minutes", cfg_path))


def general_news_enabled(cfg_path: str | None = None) -> bool:
    """Whether the poll includes general market news alongside per-symbol news."""
    return bool(_block(cfg_path).get("general_news_enabled", True))


# --- Materiality (free filter) ----------------------------------------------

def materiality_min_sentiment(cfg_path: str | None = None) -> float:
    """Absolute sentiment magnitude at or above which an event is material."""
    return float(_num("materiality_min_sentiment", cfg_path))


def materiality_keywords(cfg_path: str | None = None) -> list[str]:
    raw = _block(cfg_path).get("materiality_keywords",
                               _DEFAULTS["materiality_keywords"])
    if isinstance(raw, list):
        return [str(s).strip().lower() for s in raw if str(s).strip()]
    return [s.strip().lower() for s in str(raw or "").split(",") if s.strip()]


# --- Interpretation (the only paid stage) -----------------------------------

def adaptive_daily_llm_budget(cfg_path: str | None = None) -> int:
    """Daily interpretation budget. SEPARATE from and ADDITIVE to both the
    discovery budget and the trading council budget, so this layer can never eat
    either one's calls."""
    return int(_num("adaptive_daily_llm_budget", cfg_path))


def adaptive_est_cost_per_call_usd(cfg_path: str | None = None) -> float:
    return float(_num("adaptive_est_cost_per_call_usd", cfg_path))


def max_interpretations_per_poll(cfg_path: str | None = None) -> int:
    """Per-poll ceiling. The daily budget bounds the day; this bounds one noisy
    minute, so a single news storm cannot spend the whole day's budget at once."""
    return int(_num("max_interpretations_per_poll", cfg_path))


def interpretation_model(cfg_path: str | None = None) -> str:
    """The model that reads an escalated event. Haiku by default: this is a
    structured extraction, not a council debate, and it runs far more often than
    a council call ever should."""
    return str(_block(cfg_path).get("interpretation_model",
                                    _DEFAULTS["interpretation_model"]))


def interpretation_min_relevance(cfg_path: str | None = None) -> float:
    """How relevant the model must find an event to the instrument before the
    read is allowed to cause anything. Relevance is a MODEL output, not something
    the free filter can know, so this gate lives at the interpretation stage
    rather than in adaptive/materiality.py.
    """
    return float(_num("interpretation_min_relevance", cfg_path))


# --- Action -----------------------------------------------------------------

def action_min_severity(cfg_path: str | None = None) -> float:
    """Severity floor below which an interpretation causes nothing at all."""
    return float(_num("action_min_severity", cfg_path))


def action_max_age_seconds(cfg_path: str | None = None) -> int:
    """A queued defensive action older than this is refused by the engine.

    Stale news must not move a position. If the engine was down, or the poller
    ran long, the right answer on resume is to drop the action, not to act on a
    five-hour-old headline.
    """
    return int(_num("action_max_age_seconds", cfg_path))


def defensive_trim_fraction(cfg_path: str | None = None) -> float:
    """What fraction of a position a `trim` closes. Half by default."""
    return float(_num("defensive_trim_fraction", cfg_path))
