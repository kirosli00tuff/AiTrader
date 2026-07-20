"""Read-only readers for the operator experience (2026-07-20).

The interface is built around the engine's written reasoning. Everything here
READS: the events journal (with payloads, which carry the real numbers every
block was judged on), the per-provider council outputs, per-symbol bar
provenance and availability, the watchdog's own state, and recent bars. No
function writes anything, and app.py exposes them as GET only.

Grouping, summaries, and copy live in the frontend. This module returns
faithful rows.
"""
from __future__ import annotations

import json
import os
import sqlite3
from datetime import datetime, timezone

from api_server import stack, store
from market_data.tradeable import symbol_is_tradeable

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# Event kinds that describe the watchdog/feed story, for the diagnostics view.
WATCHDOG_KINDS = (
    "feed_substitution", "feed_restored", "symbol_unavailable",
    "symbol_available", "watchdog_restart", "engine_supervisor",
    "continuous_start", "continuous_stop", "kill_switch", "provenance_block",
)

# Council-tier decision events: the engine evaluated a setup all the way to a
# verdict and either acted or refused with numbers.
_DECISION_KINDS = ("risk_block", "trade_entry", "council_skip", "trade")


def _parse_payload(raw: str | None) -> dict:
    if not raw:
        return {}
    try:
        d = json.loads(raw)
        return d if isinstance(d, dict) else {}
    except (ValueError, TypeError):
        return {}


def activity(since_id: int = 0, limit: int = 300) -> dict:
    """Events with ids and parsed payloads, ascending, for incremental
    streaming. since_id=0 means the most recent ``limit`` events. The payload
    is the point: a block's real numbers are the most informative thing the
    engine writes."""
    limit = max(1, min(int(limit), 1000))
    if since_id > 0:
        rows = store.query(
            "SELECT id, ts, kind, venue, symbol, severity, message, "
            "payload_json FROM events WHERE id > ? ORDER BY id ASC LIMIT ?",
            (int(since_id), limit))
    else:
        rows = store.query(
            "SELECT id, ts, kind, venue, symbol, severity, message, "
            "payload_json FROM events ORDER BY id DESC LIMIT ?", (limit,))
        rows.reverse()
    for r in rows:
        r["payload"] = _parse_payload(r.pop("payload_json", None))
    latest = rows[-1]["id"] if rows else int(since_id)
    return {"events": rows, "latest_id": latest}


def events_since(last_id: int, cap: int = 200) -> list[dict]:
    """Delta feed for the WebSocket stream: everything after ``last_id``,
    ascending, capped. The cap protects the socket, not correctness: the
    client's next delta continues from the last id it received, so a burst is
    delivered across ticks rather than dropped."""
    return activity(since_id=max(0, int(last_id)), limit=cap)["events"]


def council_decisions(limit: int = 25) -> dict:
    """Decision records: each council-tier evaluation with the numbers it was
    judged on and the per-provider outputs recorded at the same moment.

    The engine writes model_outputs rows and the decision event in the same
    iteration with the same timestamp, so the join key is the event ts. A
    decision with no matching provider rows (an old DB, a fast-tier entry)
    still returns, with providers empty: the record is the decision, the
    providers are the supporting testimony.
    """
    limit = max(1, min(int(limit), 100))
    rows = store.query(
        "SELECT id, ts, kind, venue, symbol, severity, message, payload_json "
        "FROM events WHERE kind IN (?,?,?,?) ORDER BY id DESC LIMIT ?",
        (*_DECISION_KINDS, limit))
    decisions = []
    for r in rows:
        payload = _parse_payload(r.get("payload_json"))
        providers = store.query(
            "SELECT model, verdict, confidence, edge, weight "
            "FROM model_outputs WHERE ts = ? ORDER BY weight DESC", (r["ts"],))
        decisions.append({
            "id": r["id"], "ts": r["ts"], "kind": r["kind"],
            "symbol": r.get("symbol") or "",
            "message": r.get("message") or "",
            "numbers": payload, "providers": providers})
    cfg = store.load_config()
    council_cfg = (cfg.get("council") or {})
    risk_cfg = (cfg.get("risk") or {})
    try:
        from ml_factor.factor import bench_state
        benched, bench_detail = bench_state()
    except Exception as e:  # noqa: BLE001 - advisory display, never fatal
        benched, bench_detail = True, f"bench state unreadable ({type(e).__name__})"
    return {
        "decisions": decisions,
        "floors": {
            "council_min_confidence": council_cfg.get("council_min_confidence"),
            "required_model_agreement_count": risk_cfg.get(
                "required_model_agreement_count"),
            "min_directional_votes": council_cfg.get("min_directional_votes"),
        },
        "models": store.llm_models(),
        "dnn_benched": bool(benched),
        "dnn_bench_reason": str(bench_detail),
    }


def _watchlist_active(conn: sqlite3.Connection) -> list[str]:
    try:
        rows = conn.execute(
            "SELECT symbol FROM watchlist WHERE status='active' "
            "ORDER BY symbol").fetchall()
        return [r[0] for r in rows if r and r[0]]
    except sqlite3.OperationalError:
        return []


def symbol_diagnostics() -> dict:
    """Per-symbol data health: tradeable or unavailable (THE predicate),
    provenance of the newest bar, last real bar time, and the engine's own
    warm/cold word (its latest warm_state event). The terminal answer,
    promoted to the GUI."""
    now = datetime.now(timezone.utc)
    out: list[dict] = []
    db = store._db_path()
    try:
        conn = sqlite3.connect(f"file:{db}?mode=ro", uri=True, timeout=2.0)
    except Exception:
        return {"symbols": []}
    try:
        symbols = list(stack.whitelist())
        for sym in _watchlist_active(conn):
            if sym not in symbols:
                symbols.append(sym)
        for sym in symbols:
            d: dict = {"symbol": sym,
                       "tradeable": symbol_is_tradeable(conn, sym)}
            newest = conn.execute(
                "SELECT timestamp, COALESCE(source,'unknown') FROM bars "
                "WHERE symbol=? ORDER BY timestamp DESC LIMIT 1",
                (sym,)).fetchone()
            d["last_bar_ts"] = newest[0] if newest else None
            d["last_bar_source"] = newest[1] if newest else None
            real = conn.execute(
                "SELECT timestamp FROM bars WHERE symbol=? AND source IN "
                "('real_feed','backfill') ORDER BY timestamp DESC LIMIT 1",
                (sym,)).fetchone()
            d["last_real_ts"] = real[0] if real else None
            age = None
            if newest and newest[0]:
                try:
                    ts = datetime.fromisoformat(
                        str(newest[0]).replace("Z", "+00:00"))
                    age = int((now - ts).total_seconds())
                except ValueError:
                    age = None
            d["age_seconds"] = age
            d["bars_5min"] = conn.execute(
                "SELECT COUNT(*) FROM bars WHERE symbol=? AND timeframe='5min'",
                (sym,)).fetchone()[0]
            warm_row = store.query_one(
                "SELECT message, payload_json FROM events WHERE kind IN "
                "('warm_state','discovery_onboard') AND symbol=? "
                "ORDER BY id DESC LIMIT 1", (sym,))
            wp = _parse_payload((warm_row or {}).get("payload_json"))
            d["warm"] = (wp.get("state") == "warm") if wp.get("state") else None
            out.append(d)
    finally:
        conn.close()
    return {"symbols": out}


def watchdog_diagnostics() -> dict:
    """The watchdog's own state file plus the feed-story events, so a stack
    stop is visible and explained in the GUI rather than only in terminal
    output."""
    state_path = os.path.join(stack.run_dir(), "watchdog_state.json")
    state: dict = {}
    try:
        with open(state_path) as fh:
            loaded = json.load(fh)
        state = loaded if isinstance(loaded, dict) else {}
    except (OSError, ValueError):
        state = {}
    rows = store.query(
        "SELECT id, ts, kind, symbol, severity, message, payload_json "
        "FROM events WHERE kind IN ({}) ORDER BY id DESC LIMIT 60".format(
            ",".join("?" for _ in WATCHDOG_KINDS)), WATCHDOG_KINDS)
    for r in rows:
        r["payload"] = _parse_payload(r.pop("payload_json", None))
    return {"state": state, "events": rows}


def bars(symbol: str, timeframe: str = "5min", limit: int = 120) -> dict:
    """Recent bars for one symbol, oldest first, plus session change (last
    close against the first bar of the current UTC day)."""
    limit = max(1, min(int(limit), 500))
    tf = timeframe if timeframe in ("5min", "1day") else "5min"
    rows = store.query(
        "SELECT timestamp AS ts, open, high, low, close, volume, "
        "COALESCE(source,'unknown') AS source FROM bars "
        "WHERE symbol=? AND timeframe=? ORDER BY timestamp DESC LIMIT ?",
        (symbol, tf, limit))
    rows.reverse()
    last = rows[-1]["close"] if rows else None
    day = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    open_row = store.query_one(
        "SELECT open FROM bars WHERE symbol=? AND timeframe=? AND "
        "timestamp >= ? ORDER BY timestamp ASC LIMIT 1",
        (symbol, tf, f"{day}T00:00:00Z"))
    session_open = (open_row or {}).get("open")
    change_pct = None
    if last is not None and session_open:
        change_pct = (last / session_open - 1.0) * 100.0
    return {"symbol": symbol, "timeframe": tf, "bars": rows,
            "last_price": last, "session_open": session_open,
            "session_change_pct": change_pct}


def position_exits(mode: str) -> dict:
    """Open positions joined with the exit levels the native strategy logged
    at entry (trade_entry payload: stop, target, factor, regime). The numbers
    are the engine's own, recorded when it opened the position, never
    recomputed here."""
    positions = store.positions(mode)
    out = []
    for p in positions:
        if not p.get("qty"):
            continue
        entry_ev = store.query_one(
            "SELECT ts, payload_json FROM events WHERE kind='trade_entry' "
            "AND symbol=? ORDER BY id DESC LIMIT 1", (p["symbol"],))
        payload = _parse_payload((entry_ev or {}).get("payload_json"))
        out.append({**p,
                    "stop": payload.get("stop"),
                    "target": payload.get("target"),
                    "entry_factor": payload.get("factor"),
                    "entry_regime": payload.get("regime"),
                    "entry_logged_ts": (entry_ev or {}).get("ts")})
    return {"mode": mode, "positions": out}
