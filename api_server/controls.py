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
    return {
        "layers": {layer: True for layer in LAYERS},
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
    for k in ("pending_promote", "pending_rollback"):
        if k in saved:
            state[k] = saved[k]
    if isinstance(saved.get("layers"), dict):
        for layer in LAYERS:
            if layer in saved["layers"]:
                state["layers"][layer] = bool(saved["layers"][layer])
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


def request_promote() -> dict:
    summ = registry_summary()
    if not summ["can_promote"]:
        return {"ok": False,
                "error": f"promotion gated: {summ['promote_reason']}",
                "registry": summ}
    st = read_controls()
    req = {"model_id": (summ["challenger"] or {}).get("model_id"),
           "ts": _now()}
    st["pending_promote"] = req
    _write_controls(st)
    _audit("promote_request", None, req)
    return {"ok": True, "request": req,
            "note": "promote request recorded + audited; the trainer/registry "
                    "applies it, never automatically"}


def request_rollback() -> dict:
    summ = registry_summary()
    if not summ["can_rollback"]:
        return {"ok": False, "error": "no retired champion to roll back to"}
    st = read_controls()
    req = {"ts": _now()}
    st["pending_rollback"] = req
    _write_controls(st)
    _audit("rollback_request", None, req)
    return {"ok": True, "request": req}
