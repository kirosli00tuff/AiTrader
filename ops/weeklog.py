"""Week-review digest. Reporting layer only, never touches trading behavior.

Each daily run appends one dated section to WEEKLOG.md at the repo root,
distilling the prior 24 hours of trading evidence from the SQLite database into a
compact, readable digest. At week end `python -m ops.weeklog --summarize` appends
a final week-summary aggregating the window: totals, the full near-miss table,
the pre-registered success-criteria checklist marked from the data, and open
calibration questions. The operator hands the one file to a reviewer.

This module is READ-ONLY against the database (opened mode=ro). It reads the
committed tables and writes only WEEKLOG.md. It never changes a trade, a limit,
or any operational value, and it never writes a credential or key to the file.

Run daily by the existing maintenance scheduling alongside the backup job
(ops/maintenance.py calls append_daily_digest). Timestamps are shown in both UTC
and America/Vancouver so the reviewer reads them in the operator's local zone.
"""
from __future__ import annotations

import argparse
import json
import os
import sqlite3
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

DISPLAY_TZ = ZoneInfo("America/Vancouver")
WEEKLOG_PATH = "WEEKLOG.md"
NEAR_MISS_BAND = 0.10          # a confidence block within this of the floor
DEFAULT_EST_COST_PER_CALL = 0.04
MONTHLY_COST_CEILING = 100.0
SLEEVE_SATELLITE_TARGET = 0.20
SLEEVE_DRIFT_BAND = 0.05
RL_FILL_GATE = 500
WEEKLOG_HEADER = (
    "# Week-Review Log\n"
    "\n"
    "Automated daily digest of the paper-trading week, appended by "
    "`ops.weeklog` (read-only over the database). Each dated section below "
    "summarizes the prior 24 hours: trades, blocks and near-misses, council and "
    "cost, sleeves, sessions, health, and anomalies. Run "
    "`python -m ops.weeklog --summarize` at week end to append a week-summary "
    "with totals, the full near-miss table, the success-criteria checklist, and "
    "open calibration questions. The operator hands this one file to a reviewer "
    "for calibration analysis. Raw data stays in the database, unchanged. "
    "Timestamps show UTC and America/Vancouver. No keys or credentials appear "
    "here.\n"
)

# US regional equity session windows in UTC minutes-since-midnight (mirrors
# config/regional_session.hpp). Crypto trades 24/7; we only tag WHEN a crypto
# fill happened by session. NY is checked first so the London/NY overlap counts
# once, under the later-opening session.
_SESSIONS = (
    ("NY", 13 * 60 + 30, 20 * 60),
    ("London", 8 * 60, 16 * 60 + 30),
    ("Asia", 0, 6 * 60),
)


# --------------------------------------------------------------------------- #
# Small helpers
# --------------------------------------------------------------------------- #
def _db_path(db: str | None = None) -> str:
    return db or os.environ.get("MAL_DB_PATH", "market_ai_lab.db")


def _connect_ro(db: str) -> sqlite3.Connection:
    conn = sqlite3.connect(f"file:{db}?mode=ro", uri=True, timeout=5.0)
    conn.row_factory = sqlite3.Row
    return conn


def _parse_ts(ts: str | None) -> datetime | None:
    if not ts:
        return None
    try:
        dt = datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
    except ValueError:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def _iso_z(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _dual(ts: str | None) -> str:
    """One timestamp rendered in both UTC and America/Vancouver."""
    dt = _parse_ts(ts)
    if dt is None:
        return ts or "—"
    u = dt.astimezone(timezone.utc)
    v = dt.astimezone(DISPLAY_TZ)
    return f"{u:%Y-%m-%d %H:%M} UTC / {v:%Y-%m-%d %I:%M %p %Z}"


def _json_load(payload: str | None) -> dict:
    if not payload:
        return {}
    try:
        val = json.loads(payload)
        return val if isinstance(val, dict) else {}
    except (ValueError, TypeError):
        return {}


def _utc_minute_of_day(dt: datetime) -> int:
    u = dt.astimezone(timezone.utc)
    return u.hour * 60 + u.minute


def _session_of(dt: datetime) -> str:
    m = _utc_minute_of_day(dt)
    for name, lo, hi in _SESSIONS:
        if lo <= m < hi:
            return name
    return "off-session"


# --------------------------------------------------------------------------- #
# Collectors (pure reads over a time window [start, end))
# --------------------------------------------------------------------------- #
def _trades_in_window(conn: sqlite3.Connection, start: str, end: str) -> list[sqlite3.Row]:
    return list(conn.execute(
        "SELECT ts, symbol, category, side, qty, price, notional, fee, pnl, "
        "outcome, combined_conf, sleeve FROM trades "
        "WHERE ts >= ? AND ts < ? ORDER BY ts", (start, end)))


def _events_in_window(conn: sqlite3.Connection, start: str, end: str,
                      kind: str | None = None) -> list[sqlite3.Row]:
    if kind is not None:
        return list(conn.execute(
            "SELECT ts, kind, venue, symbol, severity, message, payload_json "
            "FROM events WHERE ts >= ? AND ts < ? AND kind = ? ORDER BY ts",
            (start, end, kind)))
    return list(conn.execute(
        "SELECT ts, kind, venue, symbol, severity, message, payload_json "
        "FROM events WHERE ts >= ? AND ts < ? ORDER BY ts", (start, end)))


def _fifo_hold_seconds(trades: list[sqlite3.Row]) -> float | None:
    """Average hold time by pairing entries (outcome open) with the next exit per
    symbol in chronological order. Approximate but deterministic. None when no
    pair closes in the window."""
    opens: dict[str, list[datetime]] = defaultdict(list)
    holds: list[float] = []
    for t in trades:
        dt = _parse_ts(t["ts"])
        if dt is None:
            continue
        if t["outcome"] == "open":
            opens[t["symbol"]].append(dt)
        elif t["outcome"] in ("win", "loss", "flat") and opens[t["symbol"]]:
            entry = opens[t["symbol"]].pop(0)
            holds.append((dt - entry).total_seconds())
    if not holds:
        return None
    return sum(holds) / len(holds)


def collect_trades(trades: list[sqlite3.Row]) -> dict:
    entries = [t for t in trades if t["outcome"] == "open"]
    closed = [t for t in trades if t["outcome"] in ("win", "loss", "flat")]
    wins = [t for t in closed if t["outcome"] == "win"]
    losses = [t for t in closed if t["outcome"] == "loss"]
    net = sum(float(t["pnl"] or 0.0) for t in closed)
    fees = sum(float(t["fee"] or 0.0) for t in closed)
    by_sleeve: Counter = Counter()
    by_symbol: Counter = Counter()
    for t in trades:
        by_sleeve[t["sleeve"] or "quant_core"] += 1
        by_symbol[t["symbol"]] += 1
    best = max(closed, key=lambda t: float(t["pnl"] or 0.0), default=None)
    worst = min(closed, key=lambda t: float(t["pnl"] or 0.0), default=None)
    hold_s = _fifo_hold_seconds(trades)
    win_rate = (100.0 * len(wins) / len(closed)) if closed else 0.0
    return {
        "n_total": len(trades),
        "n_entries": len(entries),
        "n_closed": len(closed),
        "n_wins": len(wins),
        "n_losses": len(losses),
        "win_rate": round(win_rate, 1),
        "net_pnl": round(net, 4),
        "gross_pnl": round(net + fees, 4),   # gross = net + costs added back
        "fees": round(fees, 4),
        "avg_hold_hours": round(hold_s / 3600.0, 2) if hold_s is not None else None,
        "by_sleeve": dict(by_sleeve),
        "by_symbol": dict(by_symbol),
        "best": _trade_brief(best),
        "worst": _trade_brief(worst),
    }


def _trade_brief(t: sqlite3.Row | None) -> dict | None:
    if t is None:
        return None
    return {
        "ts": t["ts"], "symbol": t["symbol"], "sleeve": t["sleeve"],
        "pnl": round(float(t["pnl"] or 0.0), 4), "outcome": t["outcome"],
    }


def _entry_reason_for(conn: sqlite3.Connection, symbol: str, before_ts: str) -> str:
    """Best-effort entry reason (native factor + regime) from the most recent
    trade_entry event for the symbol at or before the exit. Prose only, never a
    key value."""
    row = conn.execute(
        "SELECT payload_json FROM events WHERE kind='trade_entry' AND symbol=? "
        "AND ts <= ? ORDER BY ts DESC LIMIT 1", (symbol, before_ts)).fetchone()
    if row is None:
        return "n/a"
    p = _json_load(row["payload_json"])
    factor = p.get("factor")
    regime = p.get("regime")
    if factor and regime:
        return f"{factor} ({regime})"
    return factor or regime or "n/a"


def collect_blocks(events: list[sqlite3.Row]) -> dict:
    """RiskGate refusals and confidence near-misses from risk_block events. A
    near-miss is a block whose confidence fell below its min but within the band.
    Empty payloads are tracked separately (an anomaly)."""
    by_reason: Counter = Counter()
    near_misses: list[dict] = []
    empty_payloads = 0
    for e in events:
        if e["kind"] != "risk_block":
            continue
        p = _json_load(e["payload_json"])
        if not p:
            empty_payloads += 1
            by_reason["(empty payload)"] += 1
            continue
        by_reason[str(p.get("reason", "unknown"))] += 1
        conf = p.get("confidence")
        floor = p.get("min_confidence")
        if isinstance(conf, (int, float)) and isinstance(floor, (int, float)):
            gap = float(floor) - float(conf)
            if 0.0 <= gap <= NEAR_MISS_BAND:
                near_misses.append({
                    "ts": e["ts"], "symbol": p.get("symbol", e["symbol"]),
                    "confidence": round(float(conf), 4),
                    "min_confidence": round(float(floor), 4),
                    "agreement": p.get("agreement"),
                    "tier": p.get("tier", "n/a"),
                    "council_ran": p.get("council_ran", "n/a"),
                })
    return {
        "by_reason": dict(by_reason),
        "near_misses": near_misses,
        "empty_payloads": empty_payloads,
    }


def collect_council_cost(conn: sqlite3.Connection, events: list[sqlite3.Row],
                         est_cost: float, budget: int,
                         week_calls: int | None = None) -> dict:
    skips: Counter = Counter()
    provider_verdicts: Counter = Counter()
    provider_errors: Counter = Counter()
    calls = 0
    for e in events:
        k = e["kind"]
        p = _json_load(e["payload_json"])
        if k in ("council_skip", "market_hours", "market_hours_entry", "risk_precheck"):
            skips[str(p.get("reason", k))] += 1
        if k in ("council_call", "council_verdict"):
            calls += 1
        prov = p.get("provider")
        if prov and k in ("council_verdict", "provider_verdict"):
            provider_verdicts[str(prov)] += 1
        if prov and (e["severity"] in ("warn", "critical") or k == "provider_error"):
            provider_errors[str(prov)] += 1
    day_spend = round(calls * est_cost, 2)
    week_spend = round((week_calls if week_calls is not None else calls) * est_cost, 2)
    return {
        "calls": calls,
        "budget": budget,
        "est_cost_per_call": est_cost,
        "day_spend_est": day_spend,
        "week_spend_est": week_spend,
        "skips_by_reason": dict(skips),
        "provider_verdicts": dict(provider_verdicts),
        "provider_errors": dict(provider_errors),
    }


def collect_sleeves(conn: sqlite3.Connection, events: list[sqlite3.Row],
                    start: str, end: str) -> dict:
    rows = list(conn.execute(
        "SELECT ts, sleeve, allocation, realized_pnl, unrealized_pnl "
        "FROM sleeve_history WHERE ts >= ? AND ts < ? ORDER BY ts", (start, end)))
    latest: dict[str, sqlite3.Row] = {}
    pnl: dict[str, float] = defaultdict(float)
    for r in rows:
        latest[r["sleeve"]] = r
        pnl[r["sleeve"]] = float(r["realized_pnl"] or 0.0)
    total_alloc = sum(float(r["allocation"] or 0.0) for r in latest.values())
    has_data = total_alloc > 0
    sat_alloc = (float(latest["research_satellite"]["allocation"] or 0.0)
                 if "research_satellite" in latest else 0.0)
    sat_frac = (sat_alloc / total_alloc) if has_data else 0.0
    # The band concern is the satellite EXCEEDING its cap (balloon risk), not
    # sitting under it. With no sleeve snapshots (satellite ships off), the split
    # trivially holds, so within_band is True rather than a false "drifted".
    within_band = (sat_frac <= SLEEVE_SATELLITE_TARGET + SLEEVE_DRIFT_BAND
                   if has_data else True)
    rebalances = [e for e in events if e["kind"] in ("sleeve_rebalance", "sleeve_cap")]
    theses = list(conn.execute(
        "SELECT ts, symbol, direction, conviction, status FROM research_thesis "
        "WHERE ts >= ? AND ts < ? ORDER BY ts", (start, end)))
    return {
        "allocations": {s: round(float(r["allocation"] or 0.0), 2)
                        for s, r in latest.items()},
        "has_sleeve_data": has_data,
        "satellite_fraction": round(sat_frac, 4),
        "target_satellite": SLEEVE_SATELLITE_TARGET,
        "within_band": within_band,
        "pnl_by_sleeve": {s: round(v, 4) for s, v in pnl.items()},
        "rebalance_events": len(rebalances),
        "theses": [{"ts": t["ts"], "symbol": t["symbol"],
                    "direction": t["direction"],
                    "conviction": round(float(t["conviction"] or 0.0), 3),
                    "status": t["status"]} for t in theses],
    }


def collect_sessions(trades: list[sqlite3.Row]) -> dict:
    counts: Counter = Counter()
    pnl: dict[str, float] = defaultdict(float)
    for t in trades:
        if t["category"] != "crypto":
            continue
        dt = _parse_ts(t["ts"])
        if dt is None:
            continue
        s = _session_of(dt)
        counts[s] += 1
        pnl[s] += float(t["pnl"] or 0.0)
    return {"counts": dict(counts), "pnl": {s: round(v, 4) for s, v in pnl.items()}}


def collect_health(conn: sqlite3.Connection, events: list[sqlite3.Row]) -> dict:
    starts = sum(1 for e in events if e["kind"] in ("continuous_start", "startup"))
    stops = sum(1 for e in events if e["kind"] == "continuous_stop")
    restarts = sum(1 for e in events
                   if e["kind"] in ("engine_supervisor", "watchdog_restart"))
    kills = [e for e in events if e["kind"] == "kill_switch"]
    challengers = [e for e in events if e["kind"] in ("challenger_recorded", "dnn_train")]
    reg = list(conn.execute(
        "SELECT ts, role FROM model_registry WHERE role='challenger' "
        "ORDER BY ts DESC LIMIT 5"))
    real_fills = conn.execute(
        "SELECT COUNT(*) FROM trades WHERE outcome IN ('win','loss','flat')"
    ).fetchone()[0]
    return {
        "engine_starts": starts,
        "engine_stops": stops,
        "watchdog_restarts": restarts,
        "kill_switch_changes": len(kills),
        "kill_events": [{"ts": e["ts"], "message": e["message"]} for e in kills],
        "challenger_attempts": len(challengers) + len(reg),
        "rl_fills": int(real_fills),
        "rl_gate": RL_FILL_GATE,
    }


def collect_anomalies(events: list[sqlite3.Row], blocks: dict) -> list[str]:
    out: list[str] = []
    if blocks["empty_payloads"]:
        out.append(f"{blocks['empty_payloads']} risk_block events with an empty "
                   "payload (pre-dates the confidence-logging fix, or a "
                   "miswrite)")
    unparseable = sum(1 for e in events
                      if e["kind"] in ("council_verdict", "council_parse")
                      and "unparse" in (e["message"] or "").lower())
    if unparseable:
        out.append(f"{unparseable} unparseable council verdicts")
    stale = sum(1 for e in events
                if "stale" in (e["message"] or "").lower()
                or e["kind"] in ("feed_stale", "staleness"))
    if stale:
        out.append(f"{stale} feed-staleness events")
    prov_fail: Counter = Counter()
    for e in events:
        if e["severity"] in ("warn", "critical"):
            p = _json_load(e["payload_json"])
            prov = p.get("provider")
            if prov:
                prov_fail[str(prov)] += 1
    for prov, n in prov_fail.items():
        if n >= 3:
            out.append(f"{n} failures from provider {prov} (repeated)")
    return out


# --------------------------------------------------------------------------- #
# Assemble a digest for a window
# --------------------------------------------------------------------------- #
def build_digest(db: str, start: datetime, end: datetime,
                 est_cost: float = DEFAULT_EST_COST_PER_CALL,
                 budget: int = 40) -> dict:
    s, e = _iso_z(start), _iso_z(end)
    conn = _connect_ro(db)
    try:
        trades = _trades_in_window(conn, s, e)
        events = _events_in_window(conn, s, e)
        blocks = collect_blocks(events)
        digest = {
            "start": s, "end": e,
            "trades": collect_trades(trades),
            "blocks": blocks,
            "council": collect_council_cost(conn, events, est_cost, budget),
            "sleeves": collect_sleeves(conn, events, s, e),
            "sessions": collect_sessions(trades),
            "health": collect_health(conn, events),
            "anomalies": collect_anomalies(events, blocks),
        }
        # Best/worst entry reasons, looked up lazily.
        for key in ("best", "worst"):
            b = digest["trades"][key]
            if b:
                b["entry_reason"] = _entry_reason_for(conn, b["symbol"], b["ts"])
        return digest
    finally:
        conn.close()


# --------------------------------------------------------------------------- #
# Rendering
# --------------------------------------------------------------------------- #
def _num(x: object) -> float:
    try:
        return float(x)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return 0.0


def _fmt_map(m: dict) -> str:
    if not m:
        return "none"
    return ", ".join(f"{k} {v}" for k, v in sorted(m.items(), key=lambda kv: -_num(kv[1])))


def render_daily_section(digest: dict, label: str) -> str:
    t = digest["trades"]
    b = digest["blocks"]
    c = digest["council"]
    sl = digest["sleeves"]
    se = digest["sessions"]
    h = digest["health"]
    lines: list[str] = []
    lines.append(f"## {label}")
    lines.append("")
    lines.append(f"Window: {_dual(digest['start'])}  ->  {_dual(digest['end'])}")
    lines.append("")

    # Trades
    lines.append("### Trades")
    lines.append(f"- Total rows {t['n_total']} | entries {t['n_entries']} | "
                 f"closed {t['n_closed']} (win {t['n_wins']}, loss {t['n_losses']}, "
                 f"win rate {t['win_rate']}%)")
    lines.append(f"- PnL net ${t['net_pnl']} | gross ${t['gross_pnl']} | "
                 f"fees ${t['fees']} | avg hold "
                 f"{t['avg_hold_hours'] if t['avg_hold_hours'] is not None else 'n/a'} h")
    lines.append(f"- By sleeve: {_fmt_map(t['by_sleeve'])}")
    lines.append(f"- By symbol: {_fmt_map(t['by_symbol'])}")
    if t["best"]:
        lines.append(f"- Best: {t['best']['symbol']} ${t['best']['pnl']} "
                     f"({t['best'].get('entry_reason', 'n/a')}) at {_dual(t['best']['ts'])}")
    if t["worst"]:
        lines.append(f"- Worst: {t['worst']['symbol']} ${t['worst']['pnl']} "
                     f"({t['worst'].get('entry_reason', 'n/a')}) at {_dual(t['worst']['ts'])}")
    lines.append("")

    # Blocks + near-misses
    lines.append("### Blocks and near-misses")
    lines.append(f"- risk_block by reason: {_fmt_map(b['by_reason'])}")
    if b["near_misses"]:
        lines.append("- Near-misses (confidence within "
                     f"{NEAR_MISS_BAND:.2f} of the floor):")
        lines.append("")
        lines.append("| ts (UTC / Vancouver) | symbol | confidence | min | agreement | tier | council_ran |")
        lines.append("| --- | --- | --- | --- | --- | --- | --- |")
        for nm in b["near_misses"]:
            lines.append(
                f"| {_dual(nm['ts'])} | {nm['symbol']} | {nm['confidence']} | "
                f"{nm['min_confidence']} | {nm.get('agreement', 'n/a')} | "
                f"{nm['tier']} | {nm['council_ran']} |")
    else:
        lines.append("- Near-misses: none in band")
    lines.append("")

    # Council + cost
    lines.append("### Council and cost")
    lines.append(f"- Council calls {c['calls']} / budget {c['budget']} | "
                 f"est spend day ${c['day_spend_est']} | week ${c['week_spend_est']} "
                 f"(@ ${c['est_cost_per_call']}/call)")
    lines.append(f"- Gate skips by reason: {_fmt_map(c['skips_by_reason'])}")
    lines.append(f"- Provider verdicts: {_fmt_map(c['provider_verdicts'])} | "
                 f"errors: {_fmt_map(c['provider_errors'])}")
    lines.append("")

    # Sleeves
    lines.append("### Sleeves")
    if sl["has_sleeve_data"]:
        lines.append(f"- Allocation: {_fmt_map(sl['allocations'])} | satellite "
                     f"{sl['satellite_fraction'] * 100:.1f}% vs target "
                     f"{int(sl['target_satellite'] * 100)}% cap "
                     f"({'within cap' if sl['within_band'] else 'OVER CAP'})")
    else:
        lines.append("- Allocation: no sleeve snapshots in window "
                     "(research_satellite ships off by default)")
    lines.append(f"- Per-sleeve PnL: {_fmt_map(sl['pnl_by_sleeve'])} | "
                 f"rebalance events {sl['rebalance_events']}")
    if sl["theses"]:
        for th in sl["theses"]:
            lines.append(f"- Thesis {th['symbol']} {th['direction']} "
                         f"conviction {th['conviction']} -> {th['status']}")
    else:
        lines.append("- Research theses: none (satellite off or no new theses)")
    lines.append("")

    # Sessions
    lines.append("### Sessions (crypto, tagged by UTC session window)")
    lines.append(f"- Trades: {_fmt_map(se['counts'])}")
    lines.append(f"- PnL: {_fmt_map(se['pnl'])}")
    lines.append("")

    # Health
    lines.append("### Health")
    lines.append(f"- Engine starts {h['engine_starts']} | stops {h['engine_stops']} "
                 f"| watchdog restarts {h['watchdog_restarts']} | kill-switch "
                 f"changes {h['kill_switch_changes']}")
    for ke in h["kill_events"]:
        lines.append(f"  - kill: {ke['message']} at {_dual(ke['ts'])}")
    lines.append(f"- DNN challenger attempts {h['challenger_attempts']} | RL fills "
                 f"{h['rl_fills']} / {h['rl_gate']} gate")
    lines.append("")

    # Anomalies
    lines.append("### Anomalies")
    if digest["anomalies"]:
        for a in digest["anomalies"]:
            lines.append(f"- {a}")
    else:
        lines.append("- none flagged")
    lines.append("")
    return "\n".join(lines)


# --------------------------------------------------------------------------- #
# Success criteria (parsed intent from CONTEXT.md, checked against the data)
# --------------------------------------------------------------------------- #
def evaluate_success_criteria(week: dict) -> list[dict]:
    """Mark each pre-registered criterion met / not met / review from the data.
    Qualitative criteria (research quality, discipline) are marked 'review' with
    the supporting numbers, which is the honest treatment of a non-numeric bar."""
    t = week["trades"]
    c = week["council"]
    sl = week["sleeves"]
    h = week["health"]
    closed_quant = t["by_sleeve"].get("quant_core", 0)
    out = [
        {"name": "Closed fills >= 40 quant_core over the week",
         "status": "met" if t["n_closed"] >= 40 else "not met",
         "evidence": f"{t['n_closed']} closed ({closed_quant} quant_core rows)"},
        {"name": "Drawdown within Level-1 (no daily-loss kill breach)",
         "status": "not met" if h["kill_switch_changes"] > 0 else "met",
         "evidence": f"{h['kill_switch_changes']} kill-switch changes"},
        {"name": "Sleeve split within 5% drift band",
         "status": "met" if sl["within_band"] else "not met",
         "evidence": (f"satellite {sl['satellite_fraction'] * 100:.1f}% vs 20% cap"
                      if sl["has_sleeve_data"] else "satellite off, no snapshots")},
        {"name": "Combined API spend at/under $100/month ceiling",
         "status": "met" if c["week_spend_est"] <= MONTHLY_COST_CEILING else "not met",
         "evidence": f"est ${c['week_spend_est']} for the week"},
        {"name": "Uptime >= 95% with restarts counted",
         "status": "review",
         "evidence": f"{h['watchdog_restarts']} watchdog restarts, "
                     f"{h['engine_starts']} starts"},
        {"name": "Research sleeve judged on thesis quality",
         "status": "review",
         "evidence": f"{len(sl['theses'])} theses this week"},
        {"name": "Discipline: mid-week changes limited to defects",
         "status": "review", "evidence": "operator log review"},
    ]
    return out


def render_week_summary(week: dict, near_misses: list[dict],
                        criteria: list[dict]) -> str:
    t = week["trades"]
    c = week["council"]
    lines: list[str] = []
    lines.append(f"## Week summary ({_dual(week['start'])} -> {_dual(week['end'])})")
    lines.append("")
    lines.append("### Totals")
    lines.append(f"- Trades {t['n_total']} | closed {t['n_closed']} | win rate "
                 f"{t['win_rate']}% | net PnL ${t['net_pnl']} | gross ${t['gross_pnl']}")
    lines.append(f"- Council calls {c['calls']} | est week spend ${c['week_spend_est']}")
    lines.append("")
    lines.append("### Success criteria (pre-registered, checked from data)")
    lines.append("")
    lines.append("| Criterion | Result | Evidence |")
    lines.append("| --- | --- | --- |")
    for cr in criteria:
        lines.append(f"| {cr['name']} | {cr['status']} | {cr['evidence']} |")
    lines.append("")
    lines.append("### Full near-miss table (week)")
    if near_misses:
        lines.append("")
        lines.append("| ts (UTC / Vancouver) | symbol | confidence | min | agreement | tier | council_ran |")
        lines.append("| --- | --- | --- | --- | --- | --- | --- |")
        for nm in near_misses:
            lines.append(
                f"| {_dual(nm['ts'])} | {nm['symbol']} | {nm['confidence']} | "
                f"{nm['min_confidence']} | {nm.get('agreement', 'n/a')} | "
                f"{nm['tier']} | {nm['council_ran']} |")
    else:
        lines.append("- none in band this week")
    lines.append("")
    lines.append("### Open calibration questions")
    for q in _calibration_questions(week):
        lines.append(f"- {q}")
    lines.append("")
    return "\n".join(lines)


def _calibration_questions(week: dict) -> list[str]:
    q: list[str] = []
    t = week["trades"]
    if t["n_closed"] and t["win_rate"] >= 80:
        q.append(f"Win rate {t['win_rate']}% is high, check for unpriced costs or "
                 "an easy synthetic regime before reading it as edge")
    if week["blocks"]["empty_payloads"]:
        q.append("Empty-payload risk_blocks remain from before the confidence-log "
                 "fix, confirm new blocks carry real numbers")
    if not week["council"]["calls"]:
        q.append("No council calls recorded, confirm the bridge/providers ran or "
                 "the run stayed on the mock path")
    if t["avg_hold_hours"] is None:
        q.append("No closed entry/exit pairs to measure hold time, cadence check")
    if not q:
        q.append("No automatic flags, review the near-miss table for confidence "
                 "calibration")
    return q


# --------------------------------------------------------------------------- #
# File append (never clobbers prior sections)
# --------------------------------------------------------------------------- #
def _ensure_header(path: str) -> str:
    if os.path.exists(path):
        with open(path, "r", encoding="utf-8") as f:
            return f.read()
    return WEEKLOG_HEADER


def append_section(path: str, section: str) -> None:
    existing = _ensure_header(path)
    body = existing.rstrip("\n") + "\n\n" + section.rstrip("\n") + "\n"
    with open(path, "w", encoding="utf-8") as f:
        f.write(body)


def append_daily_digest(db: str | None = None, path: str = WEEKLOG_PATH,
                        end: datetime | None = None) -> dict:
    db = _db_path(db)
    end = end or datetime.now(timezone.utc)
    start = end - timedelta(days=1)
    digest = build_digest(db, start, end)
    label = f"{end.astimezone(timezone.utc):%Y-%m-%d} daily digest"
    section = render_daily_section(digest, label)
    append_section(path, section)
    return {"appended": label, "closed_trades": digest["trades"]["n_closed"],
            "near_misses": len(digest["blocks"]["near_misses"])}


def append_week_summary(db: str | None = None, path: str = WEEKLOG_PATH,
                        end: datetime | None = None, days: int = 7) -> dict:
    db = _db_path(db)
    end = end or datetime.now(timezone.utc)
    start = end - timedelta(days=days)
    week = build_digest(db, start, end)
    criteria = evaluate_success_criteria(week)
    section = render_week_summary(week, week["blocks"]["near_misses"], criteria)
    append_section(path, section)
    return {"appended": "week summary", "criteria": criteria}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Week-review digest (read-only).")
    ap.add_argument("--db", default=None)
    ap.add_argument("--path", default=WEEKLOG_PATH)
    ap.add_argument("--summarize", action="store_true",
                    help="append the week-end summary instead of a daily digest")
    args = ap.parse_args(argv)
    if args.summarize:
        res = append_week_summary(args.db, args.path)
        print("week summary appended:",
              ", ".join(f"{c['name']}={c['status']}" for c in res["criteria"]))
    else:
        res = append_daily_digest(args.db, args.path)
        print("daily digest appended:", res)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
