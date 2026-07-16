"""Persistence for the adaptive real-time layer.

Four tables, all NEW and all adaptive-only. Nothing here touches an operational
trading table (trades, positions, events), which the C++ engine still solely
writes. This follows the precedent of discovery/store.py owning the funnel tables
and market_data/alpaca_source.py owning ``bars``.

What is stored is the audit trail of a decision chain that costs money and can
move a position, so every stage is legible after the fact:

  adaptive_poll           one wake-up: what was asked, what it cost
  adaptive_event          every event seen, INCLUDING the ones dropped for free
  adaptive_interpretation only the escalated few, with what the model said
  adaptive_action         only the defensive requests the engine may act on

Storing the DROPPED events matters as much as storing the escalated ones. The
whole cost argument of this layer is that the free filter throws away the vast
majority; that claim is only checkable if the thrown-away events are counted.

WRITER NOTE. adaptive_action is the queue the C++ engine reads. Python is its
sole writer; the engine only reads it and reports outcomes into the events table
it already owns. So there is no shared-write table anywhere in this design.
"""
from __future__ import annotations

import sqlite3
from datetime import datetime, timezone

from .actions import DefensiveAction, REACT_SOURCE

SCHEMA_DDL = (
    """
    CREATE TABLE IF NOT EXISTS adaptive_poll (
        id                INTEGER PRIMARY KEY AUTOINCREMENT,
        ts                TEXT NOT NULL,
        symbols_polled    INTEGER DEFAULT 0,
        events_seen       INTEGER DEFAULT 0,
        events_new        INTEGER DEFAULT 0,
        events_material   INTEGER DEFAULT 0,
        events_escalated  INTEGER DEFAULT 0,
        llm_calls         INTEGER DEFAULT 0,
        actions_queued    INTEGER DEFAULT 0,
        referrals         INTEGER DEFAULT 0,
        est_cost_usd      REAL DEFAULT 0,
        budget_remaining  INTEGER DEFAULT 0,
        status            TEXT DEFAULT 'ok',
        reason            TEXT
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_adaptive_poll_ts ON adaptive_poll(ts)",
    """
    CREATE TABLE IF NOT EXISTS adaptive_event (
        id              INTEGER PRIMARY KEY AUTOINCREMENT,
        ts              TEXT NOT NULL,
        published_ts    TEXT,
        symbol          TEXT,
        headline        TEXT,
        summary         TEXT,
        source          TEXT,
        url             TEXT,
        category        TEXT,
        sentiment       REAL DEFAULT 0,
        event_type      TEXT,
        dedupe_key      TEXT UNIQUE,
        held            INTEGER DEFAULT 0,
        material        INTEGER DEFAULT 0,
        material_reason TEXT,
        escalated       INTEGER DEFAULT 0
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_adaptive_event_ts ON adaptive_event(ts)",
    "CREATE INDEX IF NOT EXISTS idx_adaptive_event_sym ON adaptive_event(symbol, ts)",
    """
    CREATE TABLE IF NOT EXISTS adaptive_interpretation (
        id           INTEGER PRIMARY KEY AUTOINCREMENT,
        event_id     INTEGER NOT NULL,
        ts           TEXT NOT NULL,
        symbol       TEXT,
        relevance    REAL DEFAULT 0,
        direction    TEXT,
        severity     REAL DEFAULT 0,
        action       TEXT,
        action_class TEXT,
        rationale    TEXT,
        model        TEXT,
        est_cost_usd REAL DEFAULT 0,
        outcome      TEXT,
        outcome_reason TEXT
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_adaptive_interp_ts ON adaptive_interpretation(ts)",
    """
    CREATE TABLE IF NOT EXISTS adaptive_action (
        id       INTEGER PRIMARY KEY AUTOINCREMENT,
        ts       TEXT NOT NULL,
        event_id INTEGER DEFAULT 0,
        symbol   TEXT NOT NULL,
        action   TEXT NOT NULL,
        reason   TEXT,
        severity REAL DEFAULT 0,
        source   TEXT NOT NULL
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_adaptive_action_ts ON adaptive_action(ts)",
)


def ensure_schema(conn: sqlite3.Connection) -> None:
    """Create the adaptive tables if absent. Idempotent."""
    for ddl in SCHEMA_DDL:
        conn.execute(ddl)


def _utcnow_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _today(ts: str | None = None) -> str:
    return (ts or _utcnow_iso())[:10]


# --- Events -----------------------------------------------------------------

def record_event(conn: sqlite3.Connection, ev: dict) -> int | None:
    """Store one observed event. Returns its id, or None when it is a duplicate.

    Deduped on ``dedupe_key``. The poll lookback is deliberately wider than the
    poll interval so a slow or missed poll loses nothing, which means overlapping
    windows are NORMAL and the same headline arrives repeatedly. Without the
    unique key, one headline would be re-escalated and re-charged every minute.
    """
    ensure_schema(conn)
    cur = conn.execute(
        "INSERT OR IGNORE INTO adaptive_event(ts,published_ts,symbol,headline,"
        "summary,source,url,category,sentiment,event_type,dedupe_key,held,"
        "material,material_reason,escalated) "
        "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (ev.get("ts") or _utcnow_iso(), ev.get("published_ts", ""),
         ev.get("symbol", ""), ev.get("headline", ""), ev.get("summary", ""),
         ev.get("source", ""), ev.get("url", ""), ev.get("category", ""),
         float(ev.get("sentiment", 0.0) or 0.0), ev.get("event_type", ""),
         ev.get("dedupe_key", ""), 1 if ev.get("held") else 0,
         1 if ev.get("material") else 0, ev.get("material_reason", ""),
         1 if ev.get("escalated") else 0))
    if cur.rowcount == 0:
        return None  # already seen
    return int(cur.lastrowid or 0)


def mark_escalated(conn: sqlite3.Connection, event_id: int) -> None:
    conn.execute("UPDATE adaptive_event SET escalated=1 WHERE id=?", (event_id,))


def recent_events(conn: sqlite3.Connection, limit: int = 100) -> list[dict]:
    """Most recent events, newest first. Read-only. Includes the dropped ones:
    seeing what was ignored, and why, is how the filter stays honest."""
    ensure_schema(conn)
    rows = conn.execute(
        "SELECT id,ts,symbol,headline,source,category,sentiment,event_type,"
        "held,material,material_reason,escalated FROM adaptive_event "
        "ORDER BY ts DESC, id DESC LIMIT ?", (limit,)).fetchall()
    return [{"id": r[0], "ts": r[1], "symbol": r[2], "headline": r[3],
             "source": r[4], "category": r[5], "sentiment": r[6],
             "event_type": r[7], "held": bool(r[8]), "material": bool(r[9]),
             "material_reason": r[10], "escalated": bool(r[11])} for r in rows]


# --- Interpretations (the only paid stage) ----------------------------------

def record_interpretation(conn: sqlite3.Connection, event_id: int,
                          interp: dict, *, model: str, cost: float,
                          outcome: str = "", outcome_reason: str = "",
                          ts: str | None = None) -> int:
    ensure_schema(conn)
    cur = conn.execute(
        "INSERT INTO adaptive_interpretation(event_id,ts,symbol,relevance,"
        "direction,severity,action,action_class,rationale,model,est_cost_usd,"
        "outcome,outcome_reason) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (event_id, ts or _utcnow_iso(), interp.get("symbol", ""),
         float(interp.get("relevance", 0.0) or 0.0),
         interp.get("direction", ""), float(interp.get("severity", 0.0) or 0.0),
         interp.get("action", ""), interp.get("action_class", ""),
         interp.get("rationale", ""), model, float(cost), outcome,
         outcome_reason))
    return int(cur.lastrowid or 0)


def llm_calls_today(conn: sqlite3.Connection, ts: str | None = None) -> int:
    """Interpretation calls spent today (UTC). The budget counter.

    Counts ROWS, not intentions: an interpretation is recorded when the call was
    actually made, so a crash between call and record can only ever UNDERCOUNT by
    one. Undercounting by one is the safe direction for a ceiling this small.
    """
    ensure_schema(conn)
    row = conn.execute(
        "SELECT COUNT(*) FROM adaptive_interpretation WHERE substr(ts,1,10)=?",
        (_today(ts),)).fetchone()
    return int(row[0] if row else 0)


def recent_interpretations(conn: sqlite3.Connection,
                           limit: int = 50) -> list[dict]:
    ensure_schema(conn)
    rows = conn.execute(
        "SELECT i.id,i.event_id,i.ts,i.symbol,i.relevance,i.direction,"
        "i.severity,i.action,i.action_class,i.rationale,i.model,i.est_cost_usd,"
        "i.outcome,i.outcome_reason,e.headline FROM adaptive_interpretation i "
        "LEFT JOIN adaptive_event e ON e.id=i.event_id "
        "ORDER BY i.ts DESC, i.id DESC LIMIT ?", (limit,)).fetchall()
    return [{"id": r[0], "event_id": r[1], "ts": r[2], "symbol": r[3],
             "relevance": r[4], "direction": r[5], "severity": r[6],
             "action": r[7], "action_class": r[8], "rationale": r[9],
             "model": r[10], "est_cost_usd": r[11], "outcome": r[12],
             "outcome_reason": r[13], "headline": r[14]} for r in rows]


# --- The engine queue -------------------------------------------------------

def queue_defensive_action(conn: sqlite3.Connection,
                           action: DefensiveAction) -> int:
    """Queue one defensive action for the engine to consume.

    The ONLY writer of adaptive_action, and it takes a ``DefensiveAction`` and
    nothing else. That is not a stylistic choice: DefensiveAction's constructor
    refuses any non-defensive action, so the type signature alone makes it
    impossible to queue an order that opens or increases a position. A caller
    holding a string cannot get here without going through that constructor.

    Queuing is not doing. The engine still has to be running, still has to have
    the defensive flag on, still checks the action's age, and still applies it
    through its own native exit path.
    """
    if not isinstance(action, DefensiveAction):  # defence in depth, not style
        raise TypeError(
            "queue_defensive_action accepts only a DefensiveAction. Aggressive "
            "actions route through the discovery funnel, never this queue.")
    ensure_schema(conn)
    cur = conn.execute(
        "INSERT INTO adaptive_action(ts,event_id,symbol,action,reason,severity,"
        "source) VALUES(?,?,?,?,?,?,?)",
        (action.ts, action.event_id, action.symbol, action.action,
         action.reason, action.severity, REACT_SOURCE))
    return int(cur.lastrowid or 0)


def recent_actions(conn: sqlite3.Connection, limit: int = 50) -> list[dict]:
    ensure_schema(conn)
    rows = conn.execute(
        "SELECT id,ts,event_id,symbol,action,reason,severity,source "
        "FROM adaptive_action ORDER BY ts DESC, id DESC LIMIT ?",
        (limit,)).fetchall()
    return [{"id": r[0], "ts": r[1], "event_id": r[2], "symbol": r[3],
             "action": r[4], "reason": r[5], "severity": r[6], "source": r[7]}
            for r in rows]


# --- Polls ------------------------------------------------------------------

def record_poll(conn: sqlite3.Connection, stats: dict,
                ts: str | None = None) -> int:
    ensure_schema(conn)
    cur = conn.execute(
        "INSERT INTO adaptive_poll(ts,symbols_polled,events_seen,events_new,"
        "events_material,events_escalated,llm_calls,actions_queued,referrals,"
        "est_cost_usd,budget_remaining,status,reason) "
        "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (ts or _utcnow_iso(), int(stats.get("symbols_polled", 0)),
         int(stats.get("events_seen", 0)), int(stats.get("events_new", 0)),
         int(stats.get("events_material", 0)),
         int(stats.get("events_escalated", 0)), int(stats.get("llm_calls", 0)),
         int(stats.get("actions_queued", 0)), int(stats.get("referrals", 0)),
         float(stats.get("est_cost_usd", 0.0)),
         int(stats.get("budget_remaining", 0)), stats.get("status", "ok"),
         stats.get("reason", "")))
    return int(cur.lastrowid or 0)


def last_poll(conn: sqlite3.Connection) -> dict | None:
    ensure_schema(conn)
    row = conn.execute(
        "SELECT ts,symbols_polled,events_seen,events_new,events_material,"
        "events_escalated,llm_calls,actions_queued,referrals,est_cost_usd,"
        "budget_remaining,status,reason FROM adaptive_poll "
        "ORDER BY ts DESC, id DESC LIMIT 1").fetchone()
    if not row:
        return None
    return {"ts": row[0], "symbols_polled": row[1], "events_seen": row[2],
            "events_new": row[3], "events_material": row[4],
            "events_escalated": row[5], "llm_calls": row[6],
            "actions_queued": row[7], "referrals": row[8],
            "est_cost_usd": row[9], "budget_remaining": row[10],
            "status": row[11], "reason": row[12]}


def counts_today(conn: sqlite3.Connection, ts: str | None = None) -> dict:
    """Today's totals for the GUI: how much was seen, how little was paid for."""
    ensure_schema(conn)
    day = _today(ts)
    row = conn.execute(
        "SELECT COUNT(*), SUM(material), SUM(escalated) FROM adaptive_event "
        "WHERE substr(ts,1,10)=?", (day,)).fetchone()
    seen = int(row[0] or 0) if row else 0
    material = int(row[1] or 0) if row else 0
    escalated = int(row[2] or 0) if row else 0
    return {"events_seen": seen, "events_material": material,
            "events_escalated": escalated,
            "events_dropped_free": seen - escalated,
            "llm_calls": llm_calls_today(conn, ts)}
