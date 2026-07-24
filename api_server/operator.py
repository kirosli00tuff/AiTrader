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
from market_data import universe
from market_data.tradeable import real_bar_rows, symbol_is_tradeable

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# Event kinds that describe the watchdog/feed story, for the diagnostics view.
WATCHDOG_KINDS = (
    "feed_substitution", "feed_restored", "symbol_unavailable",
    "symbol_available", "watchdog_restart", "engine_supervisor",
    "continuous_start", "continuous_stop", "kill_switch", "provenance_block",
    "position_unmanageable", "position_rehydrated",
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


def symbol_diagnostics() -> dict:
    """Per-symbol data health: tradeable or unavailable (THE predicate),
    provenance of the newest bar, last real bar time, and the engine's own
    warm/cold word (its latest warm_state event). The terminal answer,
    promoted to the GUI.

    The symbol set and the universe verdict both come from
    ``market_data.universe`` (2026-07-21). This used to merge stack.whitelist()
    with its own watchlist SELECT, a third independent construction of the
    union, and it named the two real provenances in a SQL predicate of its
    own, a second copy of the invariant's source set that the lexical guard
    missed only because the string was split across two source lines.

    Diagnostics deliberately reports watchlist members even while discovery is
    OFF: the engine does not trade them then, but a stale active member is
    exactly what an operator needs to see in order to prune it.
    """
    now = datetime.now(timezone.utc)
    out: list[dict] = []
    db = store._db_path()
    try:
        conn = sqlite3.connect(f"file:{db}?mode=ro", uri=True, timeout=2.0)
    except Exception:
        return {"symbols": [], "universe": {}}
    try:
        uni = universe.resolve(conn, discovery_on=True)
        for sym in universe.declared_symbols(conn, discovery_on=True):
            d: dict = {"symbol": sym,
                       "tradeable": symbol_is_tradeable(conn, sym),
                       "part": ("core" if sym in uni.declared_core
                                else "periphery")}
            newest = conn.execute(
                "SELECT timestamp, COALESCE(source,'unknown') FROM bars "
                "WHERE symbol=? ORDER BY timestamp DESC LIMIT 1",
                (sym,)).fetchone()
            d["last_bar_ts"] = newest[0] if newest else None
            d["last_bar_source"] = newest[1] if newest else None
            # Provenance comes from the invariant's own module, never a local
            # copy of the source set (the tradeable guard's rule).
            real = real_bar_rows(conn, sym, timeframe=stack.bar_timeframe(),
                                 limit=1)
            d["last_real_ts"] = real[0][0] if real else None
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
    # The universe verdict rides along so the GUI can say "3 tradeable of 8
    # declared" and show the loud condition when it collapses, rather than
    # rendering a quietly short list.
    return {"symbols": out, "universe": uni.to_dict()}


def near_misses(window_hours: int = 24, limit: int = 100) -> dict:
    """Rejected entry candidates over a window, from the entry_decision table
    (2026-07-24): the view that would have shown the fast-tier ceiling
    without a diagnostic session. Aggregated by symbol and by first refusing
    condition, plus the recent rows with their FULL condition set, the
    composed confidence, its per-factor inputs (the signals rows the engine
    persisted at the same instant), and server-computed distances from
    firing. Read-only; renders honestly on an empty or pre-migration table
    (no rows, no error)."""
    window_hours = max(1, min(int(window_hours), 24 * 30))
    limit = max(1, min(int(limit), 500))
    cutoff = datetime.fromtimestamp(
        datetime.now(timezone.utc).timestamp() - window_hours * 3600,
        tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    try:
        rows = store.query(
            "SELECT id, ts, symbol, regime, factor, first_reject, tier, "
            "confidence, edge, state_json FROM entry_decision "
            "WHERE outcome='rejected' AND ts >= ? ORDER BY id DESC LIMIT ?",
            (cutoff, limit))
        by_reject = store.query(
            "SELECT first_reject, COUNT(*) AS n FROM entry_decision "
            "WHERE outcome='rejected' AND ts >= ? GROUP BY first_reject "
            "ORDER BY n DESC", (cutoff,))
        by_symbol = store.query(
            "SELECT symbol, COUNT(*) AS n FROM entry_decision "
            "WHERE outcome='rejected' AND ts >= ? GROUP BY symbol "
            "ORDER BY n DESC", (cutoff,))
        entered = store.query_one(
            "SELECT COUNT(*) AS n FROM entry_decision "
            "WHERE outcome='entered' AND ts >= ?", (cutoff,))
    except Exception:  # noqa: BLE001 - pre-migration DB: honest empty
        return {"window_hours": window_hours, "rows": [], "by_reject": [],
                "by_symbol": [], "entered": 0, "min_confidence": None}
    cfg = store.load_config()
    min_conf = (cfg.get("risk", {}) or {}).get("min_confidence_default")
    out_rows = []
    for r in rows:
        state = _parse_payload(r.pop("state_json", None))
        # Distances from firing, computed HERE from the engine's own recorded
        # state (Task 4). Absent inputs yield absent distances, never zeros.
        d: dict = {}
        if state.get("rsi2_entry"):
            d["rsi2_above_entry"] = round(
                float(state.get("rsi2", 0)) - float(state["rsi2_entry"]), 2)
        if state.get("trend_ma"):
            d["trend_dist_pct"] = state.get("trend_dist_pct")
        if state.get("atr_sd"):
            d["atr_z"] = state.get("atr_z")
        if state.get("vol_avg") and state.get("volume_present"):
            try:
                d["volume_over_avg"] = round(
                    float(state.get("volume", 0)) / float(state["vol_avg"]), 3)
            except ZeroDivisionError:
                pass
        if r.get("confidence") is not None and min_conf is not None:
            d["confidence_gap"] = round(
                float(r["confidence"]) - float(min_conf), 4)
        factors = []
        if r.get("tier"):
            # The composition ran: its per-factor inputs are the signals rows
            # the engine persisted at the same ts.
            factors = store.query(
                "SELECT factor, bias, confidence, edge FROM signals "
                "WHERE ts=? AND symbol=? ORDER BY factor",
                (r["ts"], r["symbol"]))
        out_rows.append({**r, "state": state, "distances": d,
                         "factors": factors})
    return {"window_hours": window_hours, "rows": out_rows,
            "by_reject": by_reject, "by_symbol": by_symbol,
            "entered": int((entered or {}).get("n", 0)),
            "min_confidence": min_conf}


def factor_participation() -> dict:
    """Which layers are ACTUALLY participating, not which are nominally
    enabled (2026-07-24). Derived server-side from the same sources the
    engine reads: the control file (enable + source axes, model toggles, RL),
    the dnn bench state, bridge reachability, and each factor's newest
    persisted signal. A benched factor, an operator-chosen mock, a mock
    forced by an unreachable bridge, and a live factor reporting a low value
    each read differently, because that distinction being invisible is what
    cost the fast-tier structural defect."""
    from api_server import controls as controls_mod
    try:
        state = controls_mod.read_controls()
    except Exception:  # noqa: BLE001
        state = {}
    layers = state.get("layers", {}) or {}
    sources = state.get("layer_sources", {}) or {}
    models = state.get("models", {}) or {}
    rl_enabled = bool(state.get("rl_enabled", False))
    bridge = {}
    try:
        bridge = store.bridge_health() or {}
    except Exception:  # noqa: BLE001
        bridge = {}
    bridge_up = bool(bridge.get("reachable"))
    try:
        from ml_factor.factor import bench_state
        benched, bench_reason = bench_state()
    except Exception as e:  # noqa: BLE001
        benched, bench_reason = True, f"bench state unreadable ({type(e).__name__})"

    def last_signal(factor: str) -> dict:
        row = store.query_one(
            "SELECT ts, bias, confidence, edge FROM signals WHERE factor=? "
            "ORDER BY id DESC LIMIT 1", (factor,))
        return row or {}

    def status_for(factor: str) -> tuple[str, str]:
        if factor == "rule_based":
            return "live", "native signal, always computed in-process"
        if factor == "rl_advisory":
            if not rl_enabled:
                return "shipped_off", "rl_enabled is false (real-fill gate)"
        layer = {"llm_primary": "council", "llm_secondary": "council",
                 "llm_tertiary": "council", "dnn_advisory": "dnn_advisory",
                 "whale_signal": "whale",
                 "rl_advisory": "rl_advisory"}.get(factor, factor)
        if layer in layers and not layers.get(layer, True):
            return "disabled", "layer toggled off (out of the ensemble)"
        if factor.startswith("llm_") and models and not all(models.values()) \
                and not any(models.values()):
            return "disabled", "every council provider toggled off"
        src = sources.get(layer, "real")
        if src == "mock":
            return "mock_by_choice", "operator set this layer on-mock"
        if not bridge_up:
            return ("mock_bridge_down",
                    "bridge unreachable: the deterministic mock serves")
        if factor == "dnn_advisory" and benched:
            return "benched", str(bench_reason)
        return "live", "real service reachable"

    factors = ["rule_based", "llm_primary", "llm_secondary", "llm_tertiary",
               "dnn_advisory", "whale_signal", "rl_advisory"]
    out = []
    for f in factors:
        status, reason = status_for(f)
        out.append({"factor": f, "status": status, "reason": reason,
                    "last_signal": last_signal(f)})
    return {"factors": out, "bridge_reachable": bridge_up,
            "dnn_benched": bool(benched), "dnn_bench_reason": str(bench_reason)}


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


def _durable_exit_state(venue: str, symbol: str) -> dict:
    """The exit-state columns persisted with the position (2026-07-23), the
    durable source rehydration reads. Empty on a DB whose positions table
    predates the migration, so the trade_entry fallback below still serves."""
    try:
        row = store.query_one(
            "SELECT stop_price, target_price, factor, time_stop_bars, "
            "bars_held FROM positions WHERE venue=? AND symbol=?",
            (venue, symbol))
        return row or {}
    except Exception:  # noqa: BLE001 - pre-migration table, fall back
        return {}


def _last_price(symbol: str) -> tuple[float | None, str | None]:
    """Newest stored close for the symbol, any provenance, with its ts. The
    engine's own bars are the price authority here; nothing is fetched."""
    row = store.query_one(
        "SELECT close, timestamp FROM bars WHERE symbol=? "
        "ORDER BY timestamp DESC LIMIT 1", (symbol,))
    if not row or row.get("close") is None:
        return None, None
    return float(row["close"]), row.get("timestamp")


def _position_health(p: dict, durable: dict, stop, target,
                     unmanageable_reason: str | None) -> dict:
    """Server-side health verdict for one open position (2026-07-24). ONE
    question: is it managed. Every flag carries the number that makes it
    true, computed HERE so the GUI can never drift from the engine's own
    answer. Absent reads as absent, never as zero: a missing stop is
    missing_exit_state, not a stop at 0."""
    last, last_ts = _last_price(str(p.get("symbol", "")))
    side = str(p.get("side", "buy"))
    sign = 1.0 if side == "buy" else -1.0
    h: dict = {"last_price": last, "last_price_ts": last_ts,
               "unmanageable_reason": unmanageable_reason,
               "missing_exit_state": stop is None and target is None,
               "past_stop": False, "past_stop_pct": None,
               "past_target": False, "past_target_pct": None,
               "time_stop_overdue": False, "time_stop_overdue_bars": None}
    if last is not None and stop is not None and stop > 0:
        # A long is past its stop when price is BELOW it; a short, above.
        breach_pct = sign * (stop - last) / stop * 100.0
        if breach_pct > 0:
            h["past_stop"] = True
            h["past_stop_pct"] = round(breach_pct, 2)
    if last is not None and target is not None and target > 0:
        gain_pct = sign * (last - target) / target * 100.0
        if gain_pct > 0:
            h["past_target"] = True
            h["past_target_pct"] = round(gain_pct, 2)
    tsb = durable.get("time_stop_bars")
    held = durable.get("bars_held")
    if tsb and held is not None and int(held) >= int(tsb) > 0:
        h["time_stop_overdue"] = True
        h["time_stop_overdue_bars"] = int(held) - int(tsb)
    h["managed"] = (unmanageable_reason is None
                    and not h["missing_exit_state"])
    return h


def unmanageable_positions() -> list[dict]:
    """The engine's own position_unmanageable verdicts (critical events
    written at construction), one per still-open position: the GUI surfacing
    of a position the engine cannot manage. Reads the engine's written
    judgment, never re-derives it."""
    try:
        rows = store.query(
            "SELECT e.ts, e.venue, e.symbol, e.message, e.payload_json "
            "FROM events e JOIN positions p "
            "ON p.venue = e.venue AND p.symbol = e.symbol AND p.qty != 0 "
            "WHERE e.kind = 'position_unmanageable' AND e.id = ("
            "  SELECT MAX(id) FROM events e2 "
            "  WHERE e2.kind = 'position_unmanageable' "
            "  AND e2.venue = e.venue AND e2.symbol = e.symbol)", ())
    except Exception:  # noqa: BLE001 - advisory display, never fatal
        return []
    out = []
    for r in rows:
        payload = _parse_payload(r.get("payload_json"))
        out.append({"ts": r.get("ts"),
                    "venue": r.get("venue"),
                    "symbol": r.get("symbol"),
                    "sleeve": payload.get("sleeve"),
                    "reason": payload.get("reason") or r.get("message"),
                    "opened_ts": payload.get("opened_ts"),
                    "qty": payload.get("qty")})
    return out


def position_exits(mode: str) -> dict:
    """Open positions joined with the exit levels the engine manages them by:
    the durable exit-state columns first (persisted at entry since
    2026-07-23), else the trade_entry payload a pre-migration position left
    behind. The numbers are the engine's own, never recomputed here. Rides
    with the engine's unmanageable-position verdicts so the loud condition
    reaches the GUI beside the positions it concerns."""
    positions = store.positions(mode)
    unmanageable = unmanageable_positions()
    um_reason = {(u.get("venue"), u.get("symbol")): u.get("reason")
                 for u in unmanageable}
    out = []
    for p in positions:
        if not p.get("qty"):
            continue
        durable = _durable_exit_state(p["venue"], p["symbol"])
        entry_ev = store.query_one(
            "SELECT ts, payload_json FROM events WHERE kind='trade_entry' "
            "AND symbol=? ORDER BY id DESC LIMIT 1", (p["symbol"],))
        payload = _parse_payload((entry_ev or {}).get("payload_json"))
        stop = (durable.get("stop_price")
                if durable.get("stop_price") is not None
                else payload.get("stop"))
        target = (durable.get("target_price")
                  if durable.get("target_price") is not None
                  else payload.get("target"))
        # Position HEALTH (2026-07-24): is it managed, with the number that
        # makes each flag true, computed server-side (Task 4: the frontend
        # derives nothing).
        health = _position_health(
            p, durable, stop, target,
            um_reason.get((p.get("venue"), p.get("symbol"))))
        out.append({**p,
                    "stop": stop,
                    "target": target,
                    "entry_factor": (durable.get("factor")
                                     or payload.get("factor")),
                    "entry_regime": payload.get("regime"),
                    "entry_logged_ts": (entry_ev or {}).get("ts"),
                    "health": health})
    return {"mode": mode, "positions": out,
            "unmanageable": unmanageable}
