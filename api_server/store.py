"""Read-only data access for the API backend.

Every operational read goes through here. The connection is opened read-only
(``mode=ro``) so a bug can never write an operational table. Config values come
from the same YAML the engine loads. The bridge probe is a short-timeout local
HTTP call that reports reachability only.
"""
from __future__ import annotations

import json
import os
import sqlite3
import urllib.request
from datetime import datetime, timezone

import yaml

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_DEFAULT_DB = os.path.join(_REPO_ROOT, "market_ai_lab.db")
_DEFAULT_CFG = os.path.join(_REPO_ROOT, "config", "default_config.yaml")
_DEFAULT_BRIDGE = "http://127.0.0.1:8765"


def _db_path() -> str:
    """Resolve the operational DB path fresh each call (env-overridable)."""
    return os.environ.get("MAL_DB_PATH", _DEFAULT_DB)


def _cfg_path() -> str:
    return os.environ.get("MAL_CONFIG_PATH", _DEFAULT_CFG)


def _bridge_url() -> str:
    return os.environ.get("MAL_BRIDGE_URL", _DEFAULT_BRIDGE)

PAPER = "paper"
LIVE = "live"
MODES = (PAPER, LIVE)


def valid_mode(mode: str) -> str:
    return mode if mode in MODES else PAPER


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


# --- Connection -------------------------------------------------------------

def db_exists() -> bool:
    return os.path.exists(_db_path())


def _connect() -> sqlite3.Connection:
    uri = f"file:{_db_path()}?mode=ro"
    conn = sqlite3.connect(uri, uri=True, timeout=2.0)
    conn.row_factory = sqlite3.Row
    return conn


def query(sql: str, params: tuple = ()) -> list[dict]:
    """Run a read-only query. Returns [] if the DB or table is absent."""
    try:
        with _connect() as conn:
            rows = conn.execute(sql, params).fetchall()
        return [dict(r) for r in rows]
    except Exception:
        return []


def query_one(sql: str, params: tuple = ()) -> dict | None:
    rows = query(sql, params)
    return rows[0] if rows else None


# --- Config -----------------------------------------------------------------

def load_config() -> dict:
    try:
        with open(_cfg_path()) as fh:
            return yaml.safe_load(fh) or {}
    except Exception:
        return {}


def llm_models() -> dict:
    return {str(k): str(v)
            for k, v in (load_config().get("llm_models", {}) or {}).items()}


# --- Venue / mode helpers ---------------------------------------------------

def venue_state() -> list[dict]:
    return query(
        "SELECT venue, mode, live_enabled, credentials_connected, "
        "kill_switch_tripped, consecutive_losses, cooldown_until_ts, "
        "updated_ts FROM venue_state ORDER BY venue")


def _live_venues() -> set[str]:
    return {r["venue"] for r in venue_state() if r.get("live_enabled")}


def _mode_of(venue: str, live: set[str]) -> str:
    return LIVE if venue in live else PAPER


# --- Account / balances -----------------------------------------------------

def _latest_balances() -> list[dict]:
    return query(
        "SELECT venue, equity, cash, realized_pnl, unrealized_pnl, "
        "drawdown_pct, ts FROM account_balances b WHERE id = "
        "(SELECT MAX(id) FROM account_balances WHERE venue = b.venue) "
        "ORDER BY venue")


def account(mode: str) -> dict:
    mode = valid_mode(mode)
    live = _live_venues()
    latest = _latest_balances()
    venues = []
    totals = {"equity": 0.0, "cash": 0.0, "realized_pnl": 0.0,
              "unrealized_pnl": 0.0}
    worst_dd = 0.0
    for r in latest:
        v = r["venue"]
        if v == "AGGREGATE":
            continue
        if _mode_of(v, live) != mode:
            continue
        venues.append(r)
        for k in totals:
            totals[k] += float(r.get(k) or 0.0)
        worst_dd = min(worst_dd, float(r.get("drawdown_pct") or 0.0))
    if not venues and mode == PAPER:
        agg = next((r for r in latest if r["venue"] == "AGGREGATE"), None)
        if agg:
            for k in totals:
                totals[k] = float(agg.get(k) or 0.0)
            worst_dd = float(agg.get("drawdown_pct") or 0.0)
    return {"mode": mode, **{k: round(v, 2) for k, v in totals.items()},
            "drawdown_pct": round(worst_dd, 2), "venues": venues}


# --- Positions / orders / trades --------------------------------------------

def positions(mode: str) -> list[dict]:
    mode = valid_mode(mode)
    live = _live_venues()
    rows = query(
        "SELECT venue, symbol, market, side, qty, avg_price, notional, "
        "opened_ts, unrealized_pnl FROM positions ORDER BY venue, symbol")
    return [r for r in rows if _mode_of(r["venue"], live) == mode]


def orders(mode: str, limit: int = 50) -> list[dict]:
    mode = valid_mode(mode)
    return query(
        "SELECT id, ts, venue, symbol, side, qty, price, notional, mode, "
        "outcome, pnl FROM trades WHERE mode = ? ORDER BY id DESC LIMIT ?",
        (mode, limit))


def closed_trades(mode: str, limit: int = 200) -> list[dict]:
    mode = valid_mode(mode)
    return query(
        "SELECT id, ts, venue, symbol, side, qty, price, notional, pnl, "
        "outcome, combined_conf, combined_edge FROM trades "
        "WHERE mode = ? AND outcome IN ('win','loss') "
        "ORDER BY id DESC LIMIT ?", (mode, limit))


# --- PnL / equity -----------------------------------------------------------

def _balance_venues() -> list[str]:
    return [r["venue"]
            for r in query("SELECT DISTINCT venue FROM account_balances")]


def _equity_curve(mode: str) -> list[dict]:
    live = _live_venues()
    if mode == PAPER:
        agg = query("SELECT ts, equity FROM account_balances "
                    "WHERE venue = 'AGGREGATE' ORDER BY ts")
        if agg:
            return agg
    venues = [v for v in _balance_venues()
              if v != "AGGREGATE" and (v in live) == (mode == LIVE)]
    if not venues:
        return []
    series: dict[str, float] = {}
    for v in venues:
        for r in query("SELECT ts, equity FROM account_balances "
                       "WHERE venue = ? ORDER BY ts", (v,)):
            series[r["ts"]] = series.get(r["ts"], 0.0) + float(r.get("equity") or 0.0)
    return [{"ts": ts, "equity": round(e, 4)}
            for ts, e in sorted(series.items())]


def pnl(mode: str) -> dict:
    mode = valid_mode(mode)
    curve = _equity_curve(mode)
    closed = closed_trades(mode, 5000)
    daily: dict[str, float] = {}
    for t in closed:
        day = (t.get("ts") or "")[:10]
        if day:
            daily[day] = daily.get(day, 0.0) + float(t.get("pnl") or 0.0)
    daily_list = [{"day": d, "pnl": round(v, 4)}
                  for d, v in sorted(daily.items())]
    wins = sum(1 for t in closed if t.get("outcome") == "win")
    losses = sum(1 for t in closed if t.get("outcome") == "loss")
    decided = wins + losses
    win_rate = round(wins / decided * 100.0, 2) if decided else 0.0
    total_pl = round(sum(float(t.get("pnl") or 0.0) for t in closed), 4)
    eq = [float(r["equity"]) for r in curve if r.get("equity") is not None]
    latest = eq[-1] if eq else 0.0
    first = eq[0] if eq else 0.0
    change = round(latest - first, 4)
    change_pct = round(change / first * 100.0, 4) if first else 0.0
    mdd, peak = 0.0, None
    for v in eq:
        peak = v if peak is None else max(peak, v)
        if peak:
            mdd = min(mdd, (v / peak - 1.0) * 100.0)
    return {"mode": mode, "equity_curve": curve, "daily_pnl": daily_list,
            "win_rate": win_rate, "wins": wins, "losses": losses,
            "n_trades": len(closed), "total_pnl": total_pl,
            "equity": round(latest, 2), "equity_change": change,
            "equity_change_pct": change_pct,
            "max_drawdown_pct": round(mdd, 2)}


# --- Signals / regime -------------------------------------------------------

def regimes() -> list[dict]:
    return query("SELECT symbol, regime, adx, rvol, updated_ts "
                 "FROM regime_state ORDER BY symbol")


def signals(limit: int = 100) -> dict:
    rows = query(
        "SELECT ts, venue, symbol, factor, bias, confidence, edge "
        "FROM signals ORDER BY id DESC LIMIT ?", (limit,))
    reg = {r["symbol"]: r for r in regimes()}
    for r in rows:
        rr = reg.get(r.get("symbol"))
        r["regime"] = rr["regime"] if rr else None
    return {"signals": rows, "regimes": list(reg.values())}


# --- Council ----------------------------------------------------------------

def council() -> dict:
    latest = query(
        "SELECT m.model, m.verdict, m.confidence, m.edge, m.weight, m.ts "
        "FROM model_outputs m JOIN (SELECT model, MAX(id) AS mid "
        "FROM model_outputs GROUP BY model) l ON m.id = l.mid "
        "ORDER BY m.weight DESC")
    recent = query(
        "SELECT ts, model, verdict, confidence, edge, weight "
        "FROM model_outputs ORDER BY id DESC LIMIT 40")
    return {"models": llm_models(), "latest": latest, "recent": recent}


# --- Whale ------------------------------------------------------------------

def whale() -> dict:
    activity = query(
        "SELECT ts, source, delayed, entity, symbol, direction, value_usd "
        "FROM whale_activity ORDER BY id DESC LIMIT 100")
    history = query(
        "SELECT ts, symbol, whale_bias, whale_confidence, "
        "whale_flow_direction, whale_activity_score, whale_follow_signal, "
        "whale_contradiction_flag, whale_regime_label, agreed_with_trade, "
        "trade_outcome FROM whale_signal_history ORDER BY id DESC LIMIT 100")
    return {"activity": activity, "history": history}


# --- Risk / venues / approval -----------------------------------------------

def risk_state() -> dict:
    risk = load_config().get("risk", {}) or {}
    vs = venue_state()
    tripped = any(r.get("kill_switch_tripped") for r in vs)
    return {"level1": risk,
            "kill_switch_enabled": bool(risk.get("kill_switch_enabled", True)),
            "kill_switch_tripped": tripped, "venues": vs}


def venues_status() -> list[dict]:
    cfg = load_config().get("venues", {}) or {}
    vs = {r["venue"]: r for r in venue_state()}
    configured: dict[str, bool] = {}
    try:
        from account_manager import credentials as creds
        for c in creds.list_status():
            if c.get("kind") == "venue":
                configured[c["group"]] = configured.get(c["group"], False) or c["configured"]
    except Exception:
        pass
    out = []
    for name, vcfg in cfg.items():
        st = vs.get(name, {})
        out.append({
            "venue": name,
            "mode": vcfg.get("mode"),
            "live_enabled": bool(vcfg.get("live_enabled")),
            "live_adapter": vcfg.get("live_adapter"),
            "runtime_mode": st.get("mode"),
            "credentials_connected": bool(st.get("credentials_connected")),
            "kill_switch_tripped": bool(st.get("kill_switch_tripped")),
            "configured": configured.get(name, False),
        })
    return out


def approval() -> dict:
    ap = query_one("SELECT live_enabled, manual_confirmation, "
                   "last_checked_ts, readiness_json FROM approval_state "
                   "WHERE id = 1") or {}
    vs = venue_state()
    live_venue = next((r for r in vs if r["venue"] == "ibkr"),
                      vs[0] if vs else {})
    creds_ok = bool(live_venue.get("credentials_connected"))
    kill = bool(live_venue.get("kill_switch_tripped"))
    live_enabled = bool(ap.get("live_enabled"))
    manual = bool(ap.get("manual_confirmation"))
    mechanisms = [
        {"name": "Live approval gate passed", "key": "approval_gate",
         "passed": manual,
         "detail": "operator recorded a manual approval confirmation"},
        {"name": "Live credentials connected", "key": "credentials_connected",
         "passed": creds_ok,
         "detail": "live credentials resolve for the live venue"},
        {"name": "Kill switch clear", "key": "kill_switch",
         "passed": (not kill), "detail": "kill switch is not tripped"},
        {"name": "Live-enabled flag set", "key": "live_enabled",
         "passed": live_enabled,
         "detail": "the mode router refuses live orders unless this is set"},
    ]
    readiness = ap.get("readiness_json")
    try:
        readiness = json.loads(readiness) if readiness else None
    except Exception:
        pass
    return {"live_enabled": live_enabled, "manual_confirmation": manual,
            "last_checked_ts": ap.get("last_checked_ts"),
            "mechanisms": mechanisms, "readiness": readiness,
            "all_passed": all(m["passed"] for m in mechanisms),
            "live_venue": live_venue.get("venue")}


# --- Events / health --------------------------------------------------------

def events(limit: int = 50) -> list[dict]:
    return query(
        "SELECT ts, kind, venue, symbol, severity, message "
        "FROM events ORDER BY id DESC LIMIT ?", (limit,))


def bridge_health() -> dict:
    url = _bridge_url().rstrip("/") + "/health"
    try:
        with urllib.request.urlopen(url, timeout=0.8) as resp:  # noqa: S310
            ok = resp.status == 200
            body = json.loads(resp.read() or b"{}")
        return {"reachable": ok, "url": _bridge_url(),
                "status": body.get("status")}
    except Exception:
        return {"reachable": False, "url": _bridge_url(), "status": None}


def health() -> dict:
    present = db_exists()
    last = query_one("SELECT ts FROM events ORDER BY id DESC LIMIT 1")
    vs = venue_state()
    kill = any(r.get("kill_switch_tripped") for r in vs)
    return {"status": "ok", "db_present": present,
            "engine": {"db_present": present,
                       "last_event_ts": last["ts"] if last else None,
                       "kill_switch_tripped": kill,
                       "running": present and last is not None},
            "bridge": bridge_health()}


def stream_snapshot(mode: str) -> dict:
    mode = valid_mode(mode)
    return {"mode": mode, "ts": _now(),
            "positions": positions(mode), "orders": orders(mode, 20),
            "pnl": pnl(mode), "events": events(15)}


# --- Kill switch: operator halt request (control file, not an op table) -----
# The engine trips its own kill switch on risk breaches and reflects that in
# venue_state.kill_switch_tripped (read below). The operator can also record a
# durable HALT REQUEST here. This writes a control file next to the keystore,
# never an operational table and never the RiskGate. The C++ engine consumes
# this file at the top of every loop iteration and trips the same latching kill
# switch (see core/engine.cpp consume_operator_kill_request), then archives it
# to kill_request.processed.json so a stale request cannot re-trip on restart.

_DEFAULT_CONTROL = os.path.join(_REPO_ROOT, ".control")


def _control_dir() -> str:
    return os.environ.get("MAL_CONTROL_DIR", _DEFAULT_CONTROL)


def _kill_request_path() -> str:
    return os.path.join(_control_dir(), "kill_request.json")


def read_kill_request() -> dict:
    try:
        with open(_kill_request_path()) as fh:
            return json.load(fh)
    except Exception:
        return {"requested": False, "reason": None, "ts": None}


def write_kill_request(requested: bool, reason: str | None) -> dict:
    os.makedirs(_control_dir(), exist_ok=True)
    rec = {"requested": bool(requested), "reason": reason, "ts": _now()}
    with open(_kill_request_path(), "w") as fh:
        json.dump(rec, fh, indent=2)
    return rec


def kill_state() -> dict:
    vs = venue_state()
    tripped = any(r.get("kill_switch_tripped") for r in vs)
    return {"engine_kill_switch_tripped": tripped,
            "request": read_kill_request()}
