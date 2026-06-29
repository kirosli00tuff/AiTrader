"""Read-only SQLite access helpers for the Dash dashboard.

The C++ core is the sole writer of the operational tables; the dashboard is a
reader (the one exception is the model-weight control panel, which appends
manual overrides to ``weight_changes`` and mirrors them to a small JSON file so
a subsequent engine run can pick them up). All queries return pandas
DataFrames so the chart/table callbacks stay declarative.
"""
from __future__ import annotations

import json
import os
import sqlite3
from typing import Any

import pandas as pd

# Resolve the shared DB once. Overridable via env so ops/demo.py and tests can
# point at a scratch database.
_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB_PATH = os.environ.get("MAL_DB_PATH", os.path.join(_REPO_ROOT, "market_ai_lab.db"))
WEIGHT_OVERRIDE_PATH = os.environ.get(
    "MAL_WEIGHT_OVERRIDE_PATH", os.path.join(_REPO_ROOT, "ui", "weight_overrides.json")
)

# Canonical ensemble factors + their config-default weights. Kept in sync with
# config/default_config.yaml -> model_weights.
DEFAULT_WEIGHTS: dict[str, float] = {
    "llm_primary": 0.27,
    "llm_secondary": 0.18,
    "llm_tertiary": 0.12,
    "rule_based": 0.18,
    "dnn_rl": 0.15,
    "whale_signal": 0.10,
}


def _connect() -> sqlite3.Connection:
    # read-only; tolerate a not-yet-seeded DB.
    uri = f"file:{DB_PATH}?mode=ro"
    return sqlite3.connect(uri, uri=True, timeout=2.0)


def query(sql: str, params: tuple[Any, ...] = ()) -> pd.DataFrame:
    """Run a read-only query, returning an empty frame if the DB/table is absent."""
    try:
        with _connect() as conn:
            return pd.read_sql_query(sql, conn, params=params)
    except Exception:
        return pd.DataFrame()


def db_exists() -> bool:
    return os.path.exists(DB_PATH)


# --- Equity / PnL -----------------------------------------------------------

def equity_curve(venue: str = "AGGREGATE") -> pd.DataFrame:
    return query(
        "SELECT ts, equity, drawdown_pct, realized_pnl, unrealized_pnl "
        "FROM account_balances WHERE venue = ? ORDER BY ts",
        (venue,),
    )


def venues_with_balances() -> list[str]:
    df = query("SELECT DISTINCT venue FROM account_balances ORDER BY venue")
    return df["venue"].tolist() if not df.empty else []


def trades(limit: int = 500) -> pd.DataFrame:
    return query(
        "SELECT id, ts, venue, symbol, market, side, qty, price, notional, "
        "mode, pnl, outcome, combined_conf, combined_edge "
        "FROM trades ORDER BY id DESC LIMIT ?",
        (limit,),
    )


def positions() -> pd.DataFrame:
    return query(
        "SELECT venue, symbol, market, side, qty, avg_price, notional, "
        "opened_ts, unrealized_pnl FROM positions ORDER BY venue, symbol"
    )


def blocked_trades(limit: int = 200) -> pd.DataFrame:
    return query(
        "SELECT ts, venue, symbol, side, qty, reason, layer "
        "FROM blocked_trades ORDER BY id DESC LIMIT ?",
        (limit,),
    )


# --- Models / weights -------------------------------------------------------

def latest_model_outputs() -> pd.DataFrame:
    """Most recent verdict row per model (the verdict board)."""
    return query(
        "SELECT m.model, m.verdict, m.confidence, m.edge, m.weight, m.ts "
        "FROM model_outputs m JOIN ("
        "  SELECT model, MAX(id) AS mid FROM model_outputs GROUP BY model"
        ") last ON m.id = last.mid ORDER BY m.weight DESC"
    )


def weight_change_history(limit: int = 200) -> pd.DataFrame:
    return query(
        "SELECT ts, factor, old_weight, new_weight, source, locked "
        "FROM weight_changes ORDER BY id DESC LIMIT ?",
        (limit,),
    )


def param_history(limit: int = 200) -> pd.DataFrame:
    return query(
        "SELECT ts, param, old_value, new_value, source, reason "
        "FROM param_history ORDER BY id DESC LIMIT ?",
        (limit,),
    )


# --- Whale ------------------------------------------------------------------

def whale_activity(limit: int = 200) -> pd.DataFrame:
    return query(
        "SELECT ts, source, delayed, entity, symbol, direction, value_usd "
        "FROM whale_activity ORDER BY id DESC LIMIT ?",
        (limit,),
    )


def whale_signal_history(limit: int = 500) -> pd.DataFrame:
    return query(
        "SELECT ts, symbol, whale_bias, whale_confidence, whale_flow_direction, "
        "whale_activity_score, whale_follow_signal, whale_contradiction_flag, "
        "whale_regime_label, agreed_with_trade, trade_outcome "
        "FROM whale_signal_history ORDER BY id DESC LIMIT ?",
        (limit,),
    )


# --- State panels -----------------------------------------------------------

def venue_state() -> pd.DataFrame:
    return query(
        "SELECT venue, mode, live_enabled, credentials_connected, "
        "kill_switch_tripped, consecutive_losses, cooldown_until_ts, updated_ts "
        "FROM venue_state ORDER BY venue"
    )


def approval_state() -> pd.DataFrame:
    return query("SELECT * FROM approval_state WHERE id = 1")


def events(limit: int = 200, kind: str | None = None) -> pd.DataFrame:
    if kind:
        return query(
            "SELECT ts, kind, venue, symbol, severity, message FROM events "
            "WHERE kind = ? ORDER BY id DESC LIMIT ?",
            (kind, limit),
        )
    return query(
        "SELECT ts, kind, venue, symbol, severity, message FROM events "
        "ORDER BY id DESC LIMIT ?",
        (limit,),
    )


def model_registry() -> pd.DataFrame:
    return query(
        "SELECT ts, model_id, role, metrics_json, notes "
        "FROM model_registry ORDER BY id DESC"
    )


def set_venue_credentials_connected(venue: str, connected: bool) -> None:
    """Reflect resolved live-credential readiness into venue_state so the C++
    approval gate (`try_enable_live` -> credentials_connected) consumes it.

    This never enables live; it only records whether credentials resolve.
    """
    from datetime import datetime, timezone
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    try:
        with sqlite3.connect(DB_PATH, timeout=2.0) as conn:
            conn.execute(
                "UPDATE venue_state SET credentials_connected=?, updated_ts=? "
                "WHERE venue=?", (int(connected), ts, venue))
            conn.commit()
    except Exception:
        pass


# --- Weight overrides (the one writer path the UI owns) ---------------------

def load_weight_overrides() -> dict[str, float]:
    """Current effective weights: file override if present, else config defaults."""
    try:
        with open(WEIGHT_OVERRIDE_PATH) as fh:
            data = json.load(fh)
        weights = {k: float(data["weights"][k]) for k in DEFAULT_WEIGHTS if k in data.get("weights", {})}
        # fill any missing factor from defaults
        for k, v in DEFAULT_WEIGHTS.items():
            weights.setdefault(k, v)
        return weights
    except Exception:
        return dict(DEFAULT_WEIGHTS)


def load_locks() -> dict[str, bool]:
    try:
        with open(WEIGHT_OVERRIDE_PATH) as fh:
            data = json.load(fh)
        return {k: bool(data.get("locks", {}).get(k, False)) for k in DEFAULT_WEIGHTS}
    except Exception:
        return {k: False for k in DEFAULT_WEIGHTS}


def normalize(weights: dict[str, float]) -> dict[str, float]:
    total = sum(max(0.0, v) for v in weights.values())
    if total <= 0:
        return dict(DEFAULT_WEIGHTS)
    return {k: max(0.0, v) / total for k, v in weights.items()}


def save_weight_overrides(weights: dict[str, float], locks: dict[str, bool],
                          source: str = "manual") -> None:
    """Persist manual weight edits and append an audit row per changed factor.

    Layer-1/2 safety is untouched here: ensemble weights only influence advisory
    blending, never the deterministic RiskGate limits.
    """
    prev = load_weight_overrides()
    norm = normalize(weights)
    os.makedirs(os.path.dirname(WEIGHT_OVERRIDE_PATH), exist_ok=True)
    with open(WEIGHT_OVERRIDE_PATH, "w") as fh:
        json.dump({"weights": norm, "locks": locks}, fh, indent=2)

    # Audit each change into weight_changes (best-effort; needs a writable DB).
    from datetime import datetime, timezone
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    try:
        with sqlite3.connect(DB_PATH, timeout=2.0) as conn:
            for factor, new_w in norm.items():
                old_w = prev.get(factor, DEFAULT_WEIGHTS.get(factor, 0.0))
                if abs(old_w - new_w) > 1e-9 or locks.get(factor):
                    conn.execute(
                        "INSERT INTO weight_changes(ts, factor, old_weight, "
                        "new_weight, source, locked) VALUES(?,?,?,?,?,?)",
                        (ts, factor, old_w, new_w, source, int(locks.get(factor, False))),
                    )
            conn.commit()
    except Exception:
        pass
