"""Validated operator control surface for the React GUI (Controls page).

Every setter validates + clamps server-side, then audits the change to the
append-only events log (store.append_event) with the old and new values. No
client value is trusted. Writes land in exactly one of two validated channels:

  1. WEIGHTS -> the same override channel the Dash advanced tab owns
     (ui.db.save_weight_overrides: clamps negatives to 0, normalizes to sum 1,
     writes weight_overrides.json, and audits each changed factor into
     weight_changes).
  2. EVERYTHING ELSE -> controls.json, a control file next to the kill-request
     file (env MAL_CONTROL_DIR, else config system.control_dir, else .control).

STRUCTURAL SAFETY RULE (enforced here, asserted in tests): nothing in this
module writes a Level-1 `risk:` value, an operational STATE table, or the
RiskGate, and nothing can enable live trading. The Level-1 block is read-only
(level1()). Champion promotion is gated on meets_promotion_criteria and is only
ever a recorded, audited request, never automatic. RL enable is refused below
the rl_min_real_fills gate regardless of what the client sends.
"""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone

from api_server import store

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# Validated domains -----------------------------------------------------------
ADAPTIVE, COUNCIL, DNN, WHALE = "adaptive", "council", "dnn_advisory", "whale"
LAYERS = (ADAPTIVE, COUNCIL, DNN, WHALE)   # safety has NO toggle (always on)
# Layers that carry a mock-versus-real SOURCE axis (bridge-backed services). The
# adaptive layer has no mock-vs-real service, so it has the enable axis only.
# Safety has neither axis: always on, always real.
SOURCE_LAYERS = (COUNCIL, DNN, WHALE)
SOURCES = ("mock", "real")
# Runtime feed-mode + clock-mode toggle (Task 3), the same control-file pattern.
# The engine reads these each loop iteration and switches the loop between real
# Alpaca data and a synthetic feed, and between real and simulated time. A switch
# away from alpaca_paper with an open position is refused (never orphans it).
FEED_MODES = ("alpaca_paper", "synthetic_regimes", "replay", "flat_random_walk")
CLOCK_MODES = ("real", "simulated")
def _council_models() -> tuple[str, ...]:
    """The three council model ids straight from config (llm_primary/secondary/
    tertiary), so the per-model toggle keys never drift from the configured
    models. Falls back to the approved defaults if config is unavailable."""
    try:
        from llm_consensus.config_access import llm_model_names
        names = llm_model_names()
        ids = tuple(names[s] for s in
                    ("llm_primary", "llm_secondary", "llm_tertiary")
                    if names.get(s))
        if len(ids) == 3:
            return ids
    except Exception:
        pass
    return ("gpt-5.5", "claude-opus-4-8", "gemini-3.1-pro-preview")


COUNCIL_MODELS = _council_models()
GATE_KEY = "gate"                          # the Claude Haiku base-check gate
REGIMES = ("trending", "range_bound", "neutral")

# Server-side bounds (client values are clamped into these, never trusted).
BUDGET_MIN, BUDGET_MAX = 1, 500
COOLDOWN_MIN, COOLDOWN_MAX = 0, 1440

# Discovery tunables the operator adjusts without editing config. Every bound is
# a COST or CADENCE bound. None of them is a Level-1 risk value, and none can
# weaken one: the RiskGate judges every resulting order exactly as before.
# (min, max) per field.
DISCOVERY_BOUNDS: dict[str, tuple[int, int]] = {
    # 0 means discovery makes no council call at all: Stage A and the cheap gate
    # still run, so the operator can watch the funnel for free.
    "discovery_daily_council_budget": (0, 100),
    "max_finalists": (1, 50),
    "max_survivors": (1, 20),
    "max_council_calls_per_pass": (0, 20),
    # A pass more often than every 15 minutes would re-rank data that has not
    # moved and burn the Finnhub rate limit for nothing.
    "crypto_interval_minutes": (15, 1440),
    "equity_interval_minutes": (15, 1440),
}
# The whale surfacing weight is a float, so it is bounded separately. 0 disables
# surfacing and restores the exact pre-whale ranking. 1.0 is the ceiling: even
# there the fixed components still carry 1.0 of the normalized total, so whale
# cannot exceed half the score.
WHALE_WEIGHT_MIN, WHALE_WEIGHT_MAX = 0.0, 1.0

# Ensemble factors for the weight sliders (rl_advisory is shown read-only at 0
# on the page; it is excluded here so normalization stays over the live six).
WEIGHT_FACTORS = ("rule_based", "llm_primary", "llm_secondary", "llm_tertiary",
                  "dnn_advisory", "whale_signal")


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


# --- control-file path (mirrors the engine + kill-request resolution) -------

def _control_dir() -> str:
    env = os.environ.get("MAL_CONTROL_DIR")
    if env:
        return env
    sys_cfg = store.load_config().get("system", {}) or {}
    return sys_cfg.get("control_dir") or os.path.join(_REPO_ROOT, ".control")


def _controls_path() -> str:
    return os.path.join(_control_dir(), "controls.json")


def _weight_override_path() -> str:
    return os.environ.get(
        "MAL_WEIGHT_OVERRIDE_PATH",
        os.path.join(_REPO_ROOT, "ui", "weight_overrides.json"))


def _clamp_int(v, lo: int, hi: int) -> int:
    try:
        v = int(v)
    except (TypeError, ValueError):
        v = lo
    return max(lo, min(hi, v))


# --- defaults from config ----------------------------------------------------

def _clamp_float(v, lo: float, hi: float) -> float:
    try:
        return max(lo, min(hi, float(v)))
    except (TypeError, ValueError):
        return lo


def _defaults() -> dict:
    cfg = store.load_config()
    council = cfg.get("council", {}) or {}
    llm = cfg.get("llm", {}) or {}
    rl = cfg.get("rl", {}) or {}
    adaptive = cfg.get("adaptive", {}) or {}
    sim = cfg.get("simulation", {}) or {}
    feed = sim.get("feed_mode", "alpaca_paper")
    clock = sim.get("clock_mode", "real")
    return {
        "layers": {layer: True for layer in LAYERS},
        # Source axis, default real (full-activation default on the paper path).
        "layer_sources": {layer: "real" for layer in SOURCE_LAYERS},
        # Runtime feed/clock, defaulting from config; validated against the
        # allow-lists so a hand-edited file can never pick an unknown mode.
        "feed_mode": feed if feed in FEED_MODES else "alpaca_paper",
        "clock_mode": clock if clock in CLOCK_MODES else "real",
        "models": {m: True for m in COUNCIL_MODELS},
        "gate_enabled": bool(llm.get("gate_enabled", True)),
        "auto_promote": bool(adaptive.get("dnn_auto_promote_if_better", False)),
        "rl_enabled": bool(rl.get("rl_enabled", False)),
        "budget": {
            "council_daily_budget":
                _clamp_int(council.get("council_daily_budget", 30),
                           BUDGET_MIN, BUDGET_MAX),
            "per_symbol_cooldown_minutes":
                _clamp_int(council.get("per_symbol_council_cooldown_minutes", 60),
                           COOLDOWN_MIN, COOLDOWN_MAX),
        },
        "regime_pins": {},
        # Discovery: seeded from config, so a missing control file means the
        # SHIPPED value, which is disabled. The operator's toggle overrides it at
        # runtime, the same way feed/clock override their launch value.
        "discovery": _discovery_defaults(cfg),
        "pending_promote": None,
        "pending_rollback": None,
    }


def _discovery_defaults(cfg: dict) -> dict:
    d = cfg.get("discovery", {}) or {}

    def _i(key: str, fallback: int) -> int:
        lo, hi = DISCOVERY_BOUNDS[key]
        return _clamp_int(d.get(key, fallback), lo, hi)

    return {
        # Both flags default FALSE from config: turning either on is a
        # deliberate operator action, never an accident of a missing file.
        "discovery_enabled": bool(d.get("discovery_enabled", False)),
        "long_term_sleeve_enabled": bool(d.get("long_term_sleeve_enabled", False)),
        "discovery_daily_council_budget":
            _i("discovery_daily_council_budget", 12),
        "max_finalists": _i("max_finalists", 12),
        "max_survivors": _i("max_survivors", 5),
        "max_council_calls_per_pass": _i("max_council_calls_per_pass", 5),
        "crypto_interval_minutes": _i("crypto_interval_minutes", 60),
        "equity_interval_minutes": _i("equity_interval_minutes", 60),
        "stage_a_whale_weight": _clamp_float(d.get("stage_a_whale_weight", 0.15),
                                             WHALE_WEIGHT_MIN, WHALE_WEIGHT_MAX),
    }


def _narrowing(d: dict) -> dict:
    """Enforce that the funnel NARROWS, whatever the operator asked for.

    survivors <= finalists and council calls <= survivors. The C++ config
    validator refuses a config that violates this, so the runtime control path
    must refuse it too, or the GUI would be a way around a rule the config
    enforces. Clamping rather than rejecting keeps a well-meant adjustment usable
    and reports that it was clamped.
    """
    out = dict(d)
    out["max_survivors"] = min(out["max_survivors"], out["max_finalists"])
    out["max_council_calls_per_pass"] = min(out["max_council_calls_per_pass"],
                                            out["max_survivors"])
    return out


def read_controls() -> dict:
    """Merge the saved control file over config-derived defaults, re-validating
    every field so a hand-edited file can never widen a bound."""
    state = _defaults()
    try:
        with open(_controls_path()) as fh:
            saved = json.load(fh)
    except Exception:
        saved = {}
    for k in ("gate_enabled", "auto_promote", "rl_enabled"):
        if k in saved:
            state[k] = bool(saved[k])
    if saved.get("feed_mode") in FEED_MODES:
        state["feed_mode"] = saved["feed_mode"]
    if saved.get("clock_mode") in CLOCK_MODES:
        state["clock_mode"] = saved["clock_mode"]
    for k in ("pending_promote", "pending_rollback"):
        if k in saved:
            state[k] = saved[k]
    if isinstance(saved.get("layers"), dict):
        for layer in LAYERS:
            if layer in saved["layers"]:
                state["layers"][layer] = bool(saved["layers"][layer])
    # Core-satellite sleeve enable toggles + a manual rebalance request. Advisory
    # only, never a Level-1 value. The engine reads sleeve enable from config at
    # startup; the runtime toggle + manual rebalance mirror the control-file
    # pattern (engine consumption is a documented follow-up).
    state.setdefault("sleeves", {"quant_core": True, "research_satellite": False})
    if isinstance(saved.get("sleeves"), dict):
        for s in ("quant_core", "research_satellite"):
            if s in saved["sleeves"]:
                state["sleeves"][s] = bool(saved["sleeves"][s])
    state.setdefault("rebalance_requested", False)
    if "rebalance_requested" in saved:
        state["rebalance_requested"] = bool(saved["rebalance_requested"])
    # Discovery: re-clamp every field on read, so a hand-edited control file can
    # never widen a bound or break the narrowing rule.
    if isinstance(saved.get("discovery"), dict):
        sd = saved["discovery"]
        d = state["discovery"]
        for k in ("discovery_enabled", "long_term_sleeve_enabled"):
            if k in sd:
                d[k] = bool(sd[k])
        for k, (lo, hi) in DISCOVERY_BOUNDS.items():
            if k in sd:
                d[k] = _clamp_int(sd[k], lo, hi)
        if "stage_a_whale_weight" in sd:
            d["stage_a_whale_weight"] = _clamp_float(
                sd["stage_a_whale_weight"], WHALE_WEIGHT_MIN, WHALE_WEIGHT_MAX)
        state["discovery"] = _narrowing(d)
    if isinstance(saved.get("layer_sources"), dict):
        for layer in SOURCE_LAYERS:
            v = saved["layer_sources"].get(layer)
            if v in SOURCES:
                state["layer_sources"][layer] = v
    if isinstance(saved.get("models"), dict):
        for m in COUNCIL_MODELS:
            if m in saved["models"]:
                state["models"][m] = bool(saved["models"][m])
    if isinstance(saved.get("budget"), dict):
        b = saved["budget"]
        state["budget"]["council_daily_budget"] = _clamp_int(
            b.get("council_daily_budget",
                  state["budget"]["council_daily_budget"]),
            BUDGET_MIN, BUDGET_MAX)
        state["budget"]["per_symbol_cooldown_minutes"] = _clamp_int(
            b.get("per_symbol_cooldown_minutes",
                  state["budget"]["per_symbol_cooldown_minutes"]),
            COOLDOWN_MIN, COOLDOWN_MAX)
    if isinstance(saved.get("regime_pins"), dict):
        wl = set(whitelist())
        for sym, reg in saved["regime_pins"].items():
            if sym in wl and reg in REGIMES:
                state["regime_pins"][sym] = reg
    return state


def _write_controls(state: dict) -> None:
    os.makedirs(_control_dir(), exist_ok=True)
    out = {**state, "ts": _now()}
    # Emit flat per-layer source keys the C++ engine reads (council_source,
    # dnn_advisory_source, whale_source) derived from the nested layer_sources
    # map the GUI uses. The flat keys are distinct from the enable keys, so the
    # engine's flat JSON reader can never confuse a source with an enable toggle.
    srcs = state.get("layer_sources", {}) or {}
    for layer in SOURCE_LAYERS:
        out[f"{layer}_source"] = "mock" if srcs.get(layer) == "mock" else "real"
    # Flat per-slot council model enables the C++ engine reads (llm_primary_enabled
    # etc.), derived from the models map (keyed by model id) and the slot order.
    models = state.get("models", {}) or {}
    for slot, model_id in zip(("llm_primary", "llm_secondary", "llm_tertiary"),
                              COUNCIL_MODELS):
        out[f"{slot}_enabled"] = bool(models.get(model_id, True))
    # Flat runtime budget the engine reads (rt_ prefix so they never collide with
    # the nested budget block's keys under the tiny C++ JSON reader).
    budget = state.get("budget", {}) or {}
    if "council_daily_budget" in budget:
        out["rt_council_daily_budget"] = budget["council_daily_budget"]
    if "per_symbol_cooldown_minutes" in budget:
        out["rt_per_symbol_cooldown_minutes"] = budget["per_symbol_cooldown_minutes"]
    # Flat per-symbol regime pins the engine reads (regime_pin:<symbol>).
    for sym, regime in (state.get("regime_pins", {}) or {}).items():
        out[f"regime_pin:{sym}"] = regime
    with open(_controls_path(), "w") as fh:
        json.dump(out, fh, indent=2)


def _audit(param: str, old, new, source: str = "gui") -> None:
    store.append_event(
        "control_change", f"{param}: {old} -> {new}", severity="info",
        payload_json=json.dumps({"param": param, "old": old, "new": new,
                                 "source": source}))


# --- read helpers ------------------------------------------------------------

def whitelist() -> list[str]:
    strat = store.load_config().get("strategy", {}) or {}
    raw = str(strat.get("whitelist", "BTC/USD,ETH/USD,SPY,QQQ"))
    return [s.strip() for s in raw.split(",") if s.strip()]


def level1() -> dict:
    """Level-1 risk block, READ-ONLY. Never written by any control here."""
    return store.load_config().get("risk", {}) or {}


def real_fills() -> int:
    """Closed real fills (the RL training gate count). Canonical definition
    from ml_factor.real_dataset.count_closed_trades, read-only."""
    row = store.query_one(
        "SELECT COUNT(*) AS n FROM trades "
        "WHERE outcome IN ('win','loss','flat')")
    return int(row["n"]) if row and row.get("n") is not None else 0


def rl_gate() -> int:
    rl = store.load_config().get("rl", {}) or {}
    try:
        return int(rl.get("rl_min_real_fills", 500))
    except (TypeError, ValueError):
        return 500


def open_position_count() -> int:
    """Open native paper positions (qty > 0). Read-only. Used by the feed-switch
    safety rule so a switch away from alpaca_paper never orphans an open position.
    The engine enforces the same rule authoritatively from its in-memory state;
    this is the server-side pre-check that refuses the unsafe request up front."""
    row = store.query_one("SELECT COUNT(*) AS n FROM positions WHERE qty > 0")
    return int(row["n"]) if row and row.get("n") is not None else 0


def council_used_today() -> int:
    row = store.query_one(
        "SELECT COUNT(*) AS n FROM model_outputs WHERE substr(ts,1,10) = ?",
        (_now()[:10],))
    return int(row["n"]) if row and row.get("n") is not None else 0


def _discovery_cfg() -> dict:
    return store.load_config().get("discovery", {}) or {}


def discovery_enabled() -> bool:
    """True when the discovery funnel is on. OFF by default (operator opt-in).

    Reads the EFFECTIVE value: the operator's controls.json toggle when present,
    else the shipped config. Same precedence as feed/clock, so a missing control
    file falls back to config, which ships disabled.
    """
    return bool(read_controls()["discovery"]["discovery_enabled"])


def longterm_state() -> bool:
    """True when the long-term sleeve STRATEGY is on. OFF by default.

    Distinct from sleeves.research_satellite_enabled, which turns the SLEEVE on.
    Both must hold for a long-term position to open.
    """
    return bool(read_controls()["discovery"]["long_term_sleeve_enabled"])


# --- Prerequisites ----------------------------------------------------------
# Enabling a subsystem into a state where it cannot work is worse than leaving it
# off: it looks on, spends nothing, and the operator learns nothing. So each
# enable is gated on the things it actually needs, and a refusal says what is
# missing rather than failing quietly.

def discovery_prerequisites() -> dict:
    """What discovery needs before it can run. Never returns a key value.

    Two hard requirements:
      * a Finnhub key that RESOLVES. Stage A is the free pre-screen and it is the
        whole funnel's input. With no key every pass reports unavailable and
        nothing is ever screened.
      * the bridge up. Stage C runs the council on survivors through it. Without
        it a pass ranks and gates, then can evaluate nothing.
    """
    try:
        from discovery.finnhub_source import is_live as finnhub_live
        finnhub_ok = bool(finnhub_live())
    except Exception:  # noqa: BLE001
        finnhub_ok = False
    bridge = store.bridge_health()
    bridge_ok = bool(bridge.get("reachable"))

    checks = [
        {"key": "finnhub_key", "ok": finnhub_ok,
         "label": "Finnhub API key",
         "detail": ("resolving" if finnhub_ok else
                    "not configured. Save one in Settings under Discovery data. "
                    "Stage A is the free pre-screen and the funnel's only input, "
                    "so without it every pass reports unavailable.")},
        {"key": "bridge", "ok": bridge_ok,
         "label": "Python bridge",
         "detail": ("reachable" if bridge_ok else
                    "down. Stage C runs the council on survivors through the "
                    "bridge. Start the engine stack, or a pass will rank and "
                    "gate but evaluate nothing.")},
    ]
    return {"ok": all(c["ok"] for c in checks), "checks": checks}


def longterm_prerequisites() -> dict:
    """What the long-term sleeve needs. Never returns a key value.

    The long-term strategy is quality-and-catalyst PLUS council, so it needs the
    Finnhub screen AND the four-level framework reachable through the bridge. It
    also needs a sleeve to trade in: the strategy without
    sleeves.research_satellite_enabled has nowhere to put a position, which the
    config validator already refuses, so the GUI refuses it too.
    """
    base = discovery_prerequisites()
    sleeve_on = bool(read_controls()["sleeves"]["research_satellite"])
    cfg_on = bool((store.load_config().get("sleeves", {}) or {})
                  .get("research_satellite_enabled", False))
    checks = list(base["checks"])
    checks.append({
        "key": "research_satellite", "ok": sleeve_on and cfg_on,
        "label": "research_satellite sleeve",
        "detail": ("enabled" if (sleeve_on and cfg_on) else
                   "off. The long-term strategy has no sleeve to trade in. "
                   "Enable the sleeve first: config "
                   "sleeves.research_satellite_enabled plus the sleeve toggle."),
    })
    return {"ok": all(c["ok"] for c in checks), "checks": checks}


# --- Setters (validated, audited, control-file only) ------------------------

def set_discovery(enabled: bool) -> dict:
    """Turn the discovery funnel on or off.

    Enabling is REFUSED when a prerequisite is missing, so the operator never
    enables into a state that cannot work. Disabling is always allowed: turning a
    spender off must never be blocked by a broken dependency.
    """
    enabled = bool(enabled)
    if enabled:
        pre = discovery_prerequisites()
        if not pre["ok"]:
            missing = [c["label"] for c in pre["checks"] if not c["ok"]]
            return {"ok": False,
                    "error": f"missing prerequisite: {', '.join(missing)}",
                    "prerequisites": pre}
    st = read_controls()
    old = st["discovery"]["discovery_enabled"]
    st["discovery"]["discovery_enabled"] = enabled
    _write_controls(st)
    _audit("discovery.discovery_enabled", old, enabled)
    return {"ok": True, "discovery_enabled": enabled}


def set_long_term(enabled: bool) -> dict:
    """Turn the long-term sleeve strategy on or off. Same posture as above."""
    enabled = bool(enabled)
    if enabled:
        pre = longterm_prerequisites()
        if not pre["ok"]:
            missing = [c["label"] for c in pre["checks"] if not c["ok"]]
            return {"ok": False,
                    "error": f"missing prerequisite: {', '.join(missing)}",
                    "prerequisites": pre}
    st = read_controls()
    old = st["discovery"]["long_term_sleeve_enabled"]
    st["discovery"]["long_term_sleeve_enabled"] = enabled
    _write_controls(st)
    _audit("discovery.long_term_sleeve_enabled", old, enabled)
    return {"ok": True, "long_term_sleeve_enabled": enabled}


def set_discovery_settings(settings: dict) -> dict:
    """Adjust the discovery cost and cadence tunables.

    Every value is clamped server-side into DISCOVERY_BOUNDS, then the narrowing
    rule is re-applied, so the GUI can never produce a funnel that widens or a
    bound the config validator would refuse. Reports what was clamped rather than
    silently accepting a value it did not honor.
    """
    if not isinstance(settings, dict) or not settings:
        return {"ok": False, "error": "no settings given"}
    unknown = [k for k in settings
               if k not in DISCOVERY_BOUNDS and k != "stage_a_whale_weight"]
    if unknown:
        return {"ok": False, "error": f"unknown setting: {', '.join(unknown)}"}

    st = read_controls()
    old = dict(st["discovery"])
    d = dict(old)
    for k, v in settings.items():
        if k == "stage_a_whale_weight":
            d[k] = _clamp_float(v, WHALE_WEIGHT_MIN, WHALE_WEIGHT_MAX)
        else:
            lo, hi = DISCOVERY_BOUNDS[k]
            d[k] = _clamp_int(v, lo, hi)
    d = _narrowing(d)
    st["discovery"] = d
    _write_controls(st)
    _audit("discovery.settings", {k: old[k] for k in settings if k in old},
           {k: d[k] for k in settings if k in d})
    clamped = {k: d[k] for k, v in settings.items() if d.get(k) != v}
    return {"ok": True, "discovery": d, "clamped": clamped}


def discovery_used_today() -> int:
    """Discovery council calls spent today, across BOTH asset classes.

    Counted from discovery_pass, so it is the funnel's own spend and stays
    SEPARATE from the trading council budget (council_used_today above).
    """
    row = store.query_one(
        "SELECT COALESCE(SUM(council_calls),0) AS n FROM discovery_pass "
        "WHERE substr(ts,1,10) = ?", (_now()[:10],))
    return int(row["n"]) if row and row.get("n") is not None else 0


def discovery_state() -> dict:
    """Discovery summary for the top strip, the sleeve panel, and Controls.

    Pure read (config + control file + discovery tables). Never a key value,
    never a Level-1 write. Reports the EFFECTIVE flags and tunables (the
    operator's control file over the shipped config), the last pass per asset
    class, the watchlist size, the universe sizes, today's spend against the
    SEPARATE discovery budget, the server-side bounds, and the prerequisites.
    """
    cfg = _discovery_cfg()
    eff = read_controls()["discovery"]

    def _int(key, default):
        try:
            return int(cfg.get(key, default))
        except (TypeError, ValueError):
            return default

    def _float(key, default):
        try:
            return float(cfg.get(key, default))
        except (TypeError, ValueError):
            return default

    def _csv_len(key):
        raw = cfg.get(key, "")
        if isinstance(raw, list):
            return len([s for s in raw if str(s).strip()])
        return len([s for s in str(raw or "").split(",") if s.strip()])

    last: dict[str, str | None] = {}
    for ac in ("crypto", "equity"):
        # Most recent by TIMESTAMP, matching store.discovery_latest.
        row = store.query_one(
            "SELECT ts FROM discovery_pass WHERE asset_class = ? "
            "ORDER BY ts DESC, id DESC LIMIT 1", (ac,))
        last[ac] = row["ts"] if row else None

    wl = store.query_one(
        "SELECT COUNT(*) AS n FROM watchlist WHERE status = 'active'")
    watchlist_size = int(wl["n"]) if wl and wl.get("n") is not None else 0

    # The EFFECTIVE budget and ceilings: the operator's control file wins.
    budget = int(eff["discovery_daily_council_budget"])
    used = discovery_used_today()
    est = _float("discovery_est_cost_per_call_usd", 0.04)
    return {
        "enabled": bool(eff["discovery_enabled"]),
        "long_term_sleeve_enabled": bool(eff["long_term_sleeve_enabled"]),
        "last_pass": last,
        "watchlist_size": watchlist_size,
        "watchlist_max": _int("watchlist_max_size", 40),
        "universe": {"crypto_active_max": _int("crypto_active_max", 50),
                     "crypto_universe": _csv_len("crypto_universe"),
                     "equity_universe": _csv_len("equity_universe")},
        "ceilings": {"max_finalists": int(eff["max_finalists"]),
                     "max_survivors": int(eff["max_survivors"]),
                     "max_council_calls_per_pass":
                         int(eff["max_council_calls_per_pass"])},
        "cadence": {"crypto_interval_minutes": int(eff["crypto_interval_minutes"]),
                    "equity_interval_minutes": int(eff["equity_interval_minutes"])},
        "stage_a_whale_weight": float(eff["stage_a_whale_weight"]),
        "budget": {"daily": budget, "used_today": used,
                   "remaining": max(0, budget - used),
                   "est_cost_per_call": est,
                   "est_spend_today": round(used * est, 4)},
        # Server-side bounds, so the GUI renders the same limits it is clamped to
        # rather than hardcoding a second copy that could drift.
        "bounds": {**{k: list(v) for k, v in DISCOVERY_BOUNDS.items()},
                   "stage_a_whale_weight": [WHALE_WEIGHT_MIN, WHALE_WEIGHT_MAX]},
        "prerequisites": discovery_prerequisites(),
        "longterm_prerequisites": longterm_prerequisites(),
        # The react layer is not built. Say so here so the GUI can state it
        # rather than implying discovery reads news live.
        "react_layer_built": False,
    }


def _parse_metrics(row: dict | None) -> dict:
    if not row:
        return {}
    try:
        return json.loads(row.get("metrics_json") or "{}")
    except Exception:
        return {}


def registry_summary() -> dict:
    champ = store.query_one(
        "SELECT ts, model_id, role, metrics_json, notes FROM model_registry "
        "WHERE role='champion' ORDER BY id DESC LIMIT 1")
    chall = store.query_one(
        "SELECT ts, model_id, role, metrics_json, notes FROM model_registry "
        "WHERE role='challenger' ORDER BY id DESC LIMIT 1")
    retired = store.query_one(
        "SELECT model_id FROM model_registry WHERE role='retired' "
        "ORDER BY id DESC LIMIT 1")
    can_promote, reason = False, "no challenger recorded"
    if chall:
        try:
            from ml_factor.registry import meets_promotion_criteria
            can_promote, reason = meets_promotion_criteria(
                _parse_metrics(champ), _parse_metrics(chall))
        except Exception as e:  # criteria helper unavailable -> stay gated
            can_promote, reason = False, f"criteria check unavailable: {e}"

    def _entry(r):
        if not r:
            return None
        return {"model_id": r["model_id"], "role": r["role"], "ts": r["ts"],
                "metrics": _parse_metrics(r), "notes": r.get("notes")}

    return {"champion": _entry(champ), "challenger": _entry(chall),
            "can_rollback": bool(retired),
            "can_promote": bool(can_promote), "promote_reason": reason}


# --- weight channel (reuses the Dash validated override path) ---------------

def _uidb():
    """Import the Dash weight-override channel and pin its paths to the current
    env, so the validated write lands in the right (temp or real) files
    regardless of import order."""
    from ui import db as uidb
    uidb.DB_PATH = store._db_path()
    uidb.WEIGHT_OVERRIDE_PATH = _weight_override_path()
    return uidb


def _default_weights() -> dict:
    try:
        return dict(_uidb().DEFAULT_WEIGHTS)
    except Exception:
        return {"llm_primary": 0.27, "llm_secondary": 0.18, "llm_tertiary": 0.12,
                "rule_based": 0.18, "dnn_advisory": 0.15, "whale_signal": 0.10}


def _effective_weights() -> dict:
    try:
        return _uidb().load_weight_overrides()
    except Exception:
        return dict(_default_weights())


# --- full read for GET /controls --------------------------------------------

def control_state() -> dict:
    st = read_controls()
    fills, gate = real_fills(), rl_gate()
    return {
        "layers": st["layers"],
        "layer_sources": st["layer_sources"],
        "source_layers": list(SOURCE_LAYERS),
        "feed_mode": st["feed_mode"],
        "clock_mode": st["clock_mode"],
        "feed_modes": list(FEED_MODES),
        "clock_modes": list(CLOCK_MODES),
        "open_positions": open_position_count(),
        "models": st["models"],
        "gate_enabled": st["gate_enabled"],
        "auto_promote": st["auto_promote"],
        "budget": st["budget"],
        "budget_bounds": {"budget": [BUDGET_MIN, BUDGET_MAX],
                          "cooldown": [COOLDOWN_MIN, COOLDOWN_MAX]},
        "council_used_today": council_used_today(),
        "rl": {"enabled": st["rl_enabled"], "min_real_fills": gate,
               "real_fills": fills, "can_enable": fills >= gate},
        "regime_pins": st["regime_pins"],
        "regimes": list(REGIMES),
        "weights": _effective_weights(),
        "default_weights": _default_weights(),
        "weight_factors": list(WEIGHT_FACTORS),
        "level1": level1(),
        "registry": registry_summary(),
        "whitelist": whitelist(),
        "pending_promote": st["pending_promote"],
        "pending_rollback": st["pending_rollback"],
    }


# --- validated setters -------------------------------------------------------

def set_weights(weights: dict) -> dict:
    clean: dict[str, float] = {}
    for f in WEIGHT_FACTORS:
        if f in weights:
            try:
                clean[f] = max(0.0, min(1.0, float(weights[f])))
            except (TypeError, ValueError):
                continue
    if not clean:
        return {"ok": False, "error": "no valid weights supplied",
                "weights": _effective_weights()}
    prev = _effective_weights()
    merged = {**prev, **clean}                 # normalize over all live factors
    try:
        uidb = _uidb()
        uidb.save_weight_overrides(merged, {f: False for f in merged},
                                   source="manual")
        eff = uidb.load_weight_overrides()
    except Exception as e:
        return {"ok": False, "error": f"weight channel unavailable: {e}",
                "weights": prev}
    _audit("weights",
           {k: round(prev.get(k, 0.0), 4) for k in eff},
           {k: round(eff[k], 4) for k in eff})
    return {"ok": True, "weights": eff}


def set_layer(layer: str, enabled: bool) -> dict:
    if layer == "safety":
        return {"ok": False,
                "error": "safety layer is always on and has no toggle"}
    if layer not in LAYERS:
        return {"ok": False, "error": f"unknown layer: {layer}"}
    st = read_controls()
    old = st["layers"][layer]
    st["layers"][layer] = bool(enabled)
    _write_controls(st)
    _audit(f"layer.{layer}", old, bool(enabled))
    return {"ok": True, "layer": layer, "enabled": bool(enabled)}


def sleeve_state() -> dict:
    """Core-satellite allocation panel data: live per-sleeve capital, the target
    split, drift band, hard cap, enable toggles, and a rebalance-due flag. Pure
    read (config + positions), never a key value, never a Level-1 write."""
    sl = store.load_config().get("sleeves", {}) or {}
    def _f(k, d):
        try:
            return float(sl.get(k, d))
        except (TypeError, ValueError):
            return d
    core_target = _f("quant_core_target_pct", 0.80)
    sat_target = _f("research_satellite_target_pct", 0.20)
    band = _f("drift_band_pct", 0.05)
    alloc = store.sleeve_allocation()
    total = alloc.get("invested_total", 0.0) or 0.0
    sat_val = alloc["research_satellite"]["allocation"]
    core_val = alloc["quant_core"]["allocation"]
    sat_share = (sat_val / total) if total > 0 else 0.0
    # A rebalance is due when the satellite share drifts past its band.
    rebalance_due = total > 0 and (
        sat_share > sat_target + band or sat_share < sat_target - band)
    st = read_controls()
    return {
        "targets": {"quant_core": core_target, "research_satellite": sat_target},
        "drift_band": band,
        "hard_cap_pct": sat_target + band,
        "allocation": {"quant_core": core_val, "research_satellite": sat_val,
                       "invested_total": total},
        "satellite_share": round(sat_share, 4),
        "rebalance_due": bool(rebalance_due),
        "enabled": st.get("sleeves", {"quant_core": True,
                                      "research_satellite": False}),
        "research_satellite_config_enabled":
            bool(sl.get("research_satellite_enabled", False)),
        "open_positions": {
            "quant_core": alloc["quant_core"]["open_positions"],
            "research_satellite": alloc["research_satellite"]["open_positions"]},
    }


def set_sleeve(sleeve: str, enabled: bool) -> dict:
    """Toggle a core-satellite sleeve enable (quant_core | research_satellite).
    Validated server-side; writes the control file, never a Level-1 value."""
    if sleeve not in ("quant_core", "research_satellite"):
        return {"ok": False, "error": f"unknown sleeve: {sleeve}"}
    st = read_controls()
    old = st["sleeves"].get(sleeve)
    st["sleeves"][sleeve] = bool(enabled)
    _write_controls(st)
    _audit(f"sleeve.{sleeve}", old, bool(enabled))
    return {"ok": True, "sleeve": sleeve, "enabled": bool(enabled)}


def request_rebalance() -> dict:
    """Request a manual sleeve rebalance. Writes a control-file flag (the engine's
    normal drift/scheduled rebalance runs through the RiskGate-approved exit path).
    Never a Level-1 value, never a forced bypass."""
    st = read_controls()
    st["rebalance_requested"] = True
    _write_controls(st)
    _audit("sleeve.rebalance_requested", False, True)
    return {"ok": True, "rebalance_requested": True}


def set_source(layer: str, source: str) -> dict:
    """Set a layer's SOURCE axis (mock/real), distinct from the enable toggle.

    Refuses the safety layer (no axis, always real) and the adaptive layer (no
    mock-vs-real service). The change takes effect on the engine's next
    iteration and is audited to the event log as layer_source.
    """
    if layer == "safety":
        return {"ok": False,
                "error": "safety layer is always real and has no source toggle"}
    if layer not in SOURCE_LAYERS:
        return {"ok": False,
                "error": f"layer has no mock/real source axis: {layer}"}
    source = str(source).strip().lower()
    if source not in SOURCES:
        return {"ok": False, "error": f"source must be one of {SOURCES}"}
    st = read_controls()
    old = st["layer_sources"][layer]
    st["layer_sources"][layer] = source
    _write_controls(st)
    _audit(f"source.{layer}", old, source)
    return {"ok": True, "layer": layer, "source": source}


def set_feed_clock(feed_mode: str, clock_mode: str) -> dict:
    """Set the runtime feed and clock mode (Task 3), validated server-side.

    Open-position safety rule: a switch AWAY from alpaca_paper while a paper
    position is open is REFUSED, so it never orphans that position. Close the
    position, or let native exits flatten it, before switching feeds. A clock
    switch is always safe. The change takes effect on the engine's next
    iteration and is audited to the event log; the engine enforces the same rule.
    """
    feed_mode = str(feed_mode).strip()
    clock_mode = str(clock_mode).strip()
    if feed_mode not in FEED_MODES:
        return {"ok": False, "error": f"feed_mode must be one of {FEED_MODES}"}
    if clock_mode not in CLOCK_MODES:
        return {"ok": False, "error": f"clock_mode must be one of {CLOCK_MODES}"}
    st = read_controls()
    cur_feed, cur_clock = st["feed_mode"], st["clock_mode"]
    open_positions = open_position_count()
    if (cur_feed == "alpaca_paper" and feed_mode != "alpaca_paper"
            and open_positions > 0):
        return {"ok": False,
                "error": (f"refused: {open_positions} open paper position(s). "
                          "Switching away from alpaca_paper would orphan them. "
                          "Close them, or let native exits flatten them, first."),
                "open_positions": open_positions,
                "feed_mode": cur_feed, "clock_mode": cur_clock}
    old = {"feed_mode": cur_feed, "clock_mode": cur_clock}
    st["feed_mode"] = feed_mode
    st["clock_mode"] = clock_mode
    _write_controls(st)
    _audit("feed_clock", old, {"feed_mode": feed_mode, "clock_mode": clock_mode})
    return {"ok": True, "feed_mode": feed_mode, "clock_mode": clock_mode,
            "open_positions": open_positions}


def set_model(model: str, enabled: bool) -> dict:
    st = read_controls()
    if model == GATE_KEY:
        old = st["gate_enabled"]
        st["gate_enabled"] = bool(enabled)
        _write_controls(st)
        _audit("gate_enabled", old, bool(enabled))
        return {"ok": True, "model": model, "enabled": bool(enabled)}
    if model not in COUNCIL_MODELS:
        return {"ok": False, "error": f"unknown council model: {model}"}
    old = st["models"][model]
    st["models"][model] = bool(enabled)
    _write_controls(st)
    _audit(f"model.{model}", old, bool(enabled))
    return {"ok": True, "model": model, "enabled": bool(enabled)}


def set_rl(enabled: bool) -> dict:
    fills, gate = real_fills(), rl_gate()
    if enabled and fills < gate:
        return {"ok": False,
                "error": f"RL enable refused: {fills} real fills < {gate} gate",
                "real_fills": fills, "min_real_fills": gate, "enabled": False}
    st = read_controls()
    old = st["rl_enabled"]
    st["rl_enabled"] = bool(enabled)
    _write_controls(st)
    _audit("rl_enabled", old, bool(enabled))
    return {"ok": True, "enabled": bool(enabled),
            "real_fills": fills, "min_real_fills": gate}


def set_auto_promote(enabled: bool) -> dict:
    st = read_controls()
    old = st["auto_promote"]
    st["auto_promote"] = bool(enabled)
    _write_controls(st)
    _audit("auto_promote", old, bool(enabled))
    return {"ok": True, "enabled": bool(enabled)}


def set_budget(daily: int, cooldown: int) -> dict:
    d = _clamp_int(daily, BUDGET_MIN, BUDGET_MAX)
    c = _clamp_int(cooldown, COOLDOWN_MIN, COOLDOWN_MAX)
    clamped = (d != daily) or (c != cooldown)
    st = read_controls()
    old = dict(st["budget"])
    st["budget"] = {"council_daily_budget": d,
                    "per_symbol_cooldown_minutes": c}
    _write_controls(st)
    _audit("budget", old, st["budget"])
    return {"ok": True, "budget": st["budget"], "clamped": clamped}


def set_regime(symbol: str, regime: str | None) -> dict:
    if symbol not in set(whitelist()):
        return {"ok": False, "error": f"symbol not in whitelist: {symbol}"}
    if regime is not None and regime not in REGIMES:
        return {"ok": False, "error": f"invalid regime: {regime}"}
    st = read_controls()
    old = st["regime_pins"].get(symbol)
    if regime is None:
        st["regime_pins"].pop(symbol, None)
    else:
        st["regime_pins"][symbol] = regime
    _write_controls(st)
    _audit(f"regime_pin.{symbol}", old, regime)
    return {"ok": True, "symbol": symbol, "regime": regime,
            "regime_pins": st["regime_pins"]}


def _registry_conn():
    """Open a read-write connection to the shared DB for a registry role update.
    Promotion/rollback are the only registry writes here and are gated + audited.
    The model_registry table is the Python trainer's, not a C++ operational table."""
    import sqlite3
    return sqlite3.connect(store._db_path(), timeout=2.0)


def request_promote() -> dict:
    """Execute a manual dnn champion promotion through the registry path, gated by
    meets_promotion_criteria (can_promote) so a runtime promote cannot bypass the
    criteria. Retires the current champion, installs the challenger, audits the
    change with old and new champion. The frontend requires a confirm."""
    summ = registry_summary()
    if not summ["can_promote"]:
        return {"ok": False,
                "error": f"promotion gated: {summ['promote_reason']}",
                "registry": summ}
    chall = summ["challenger"] or {}
    challenger_id = chall.get("model_id")
    old_champ = (summ["champion"] or {}).get("model_id")
    from ml_factor import registry as reg
    try:
        conn = _registry_conn()
        try:
            reg.promote(conn, challenger_id, chall.get("metrics", {}),
                        "manual GUI promote")
            conn.commit()
        finally:
            conn.close()
    except Exception as e:
        return {"ok": False, "error": f"promote failed: {e}"}
    st = read_controls()
    st["pending_promote"] = {"model_id": challenger_id, "ts": _now(),
                             "executed": True}
    _write_controls(st)
    _audit("promote", old_champ, challenger_id)
    return {"ok": True, "champion": challenger_id, "retired": old_champ}


def request_rollback() -> dict:
    """Execute a manual rollback to the previous champion through the registry
    rollback path, audited with old and new champion. The frontend requires a
    confirm. No-op refusal if there is no retired champion to roll back to."""
    summ = registry_summary()
    if not summ["can_rollback"]:
        return {"ok": False, "error": "no retired champion to roll back to"}
    old_champ = (summ["champion"] or {}).get("model_id")
    from ml_factor import registry as reg
    try:
        conn = _registry_conn()
        try:
            restored = reg.rollback(conn, "manual GUI rollback")
            conn.commit()
        finally:
            conn.close()
    except Exception as e:
        return {"ok": False, "error": f"rollback failed: {e}"}
    if not restored:
        return {"ok": False, "error": "no retired champion to roll back to"}
    st = read_controls()
    st["pending_rollback"] = {"ts": _now(), "restored": restored,
                              "executed": True}
    _write_controls(st)
    _audit("rollback", old_champ, restored)
    return {"ok": True, "champion": restored, "was": old_champ}
