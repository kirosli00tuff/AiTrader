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
        "pending_promote": None,
        "pending_rollback": None,
    }


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
