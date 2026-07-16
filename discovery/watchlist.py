"""The dynamic watchlist: a living candidate list both sleeves draw from.

Discovery adds an instrument when it survives to Stage C. The list prunes itself
when a signal goes stale (no pass re-confirmed it inside ``watchlist_stale_hours``)
or when a thesis breaks. It is deliberately small: the universe is the outer edge
of the funnel, the watchlist is the narrow end.

EVENT-SOURCED ON PURPOSE. Every mutation goes through ``apply_event`` with an
explicit source, and each one is journalled to ``watchlist_event``. That is the
bridge to the deferred real-time react layer: when that layer ships it emits the
same add/remove events from a new source and needs no rewrite here. Today only
``discovery`` and ``prune`` are accepted sources. Every other source is REFUSED
(``source_not_enabled``), so the structure exists without the behavior and the
react layer stays off until it is deliberately built and gated. See CONTEXT.md.

Writer note: this module owns the discovery tables, following the precedent of
market_data/alpaca_source.py writing ``bars`` and ml_factor/registry.py writing
``model_registry``. The C++ engine remains the sole writer of the OPERATIONAL
trading tables (trades, positions, events). It only READS the watchlist, and only
when discovery is enabled.
"""
from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

# Sources allowed to mutate the watchlist TODAY. The reserved names are the
# forward-compatibility seam: they parse, they are refused, and enabling them is
# a deliberate later build, never an accident.
ACTIVE_SOURCES = ("discovery", "prune")
RESERVED_SOURCES = ("adaptive_react", "manual")

VALID_ACTIONS = ("add", "remove")
VALID_SLEEVES = ("quant_core", "research_satellite")

SCHEMA_DDL = (
    """
    CREATE TABLE IF NOT EXISTS watchlist (
        id             INTEGER PRIMARY KEY AUTOINCREMENT,
        symbol         TEXT NOT NULL UNIQUE,
        asset_class    TEXT,
        added_ts       TEXT NOT NULL,
        updated_ts     TEXT NOT NULL,
        source         TEXT NOT NULL,
        reason         TEXT,
        sleeve_target  TEXT DEFAULT 'quant_core',
        score          REAL DEFAULT 0,
        status         TEXT DEFAULT 'active',
        removed_ts     TEXT,
        removed_reason TEXT
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_watchlist_status ON watchlist(status, symbol)",
    """
    CREATE TABLE IF NOT EXISTS watchlist_event (
        id      INTEGER PRIMARY KEY AUTOINCREMENT,
        ts      TEXT NOT NULL,
        action  TEXT NOT NULL,
        symbol  TEXT NOT NULL,
        source  TEXT NOT NULL,
        reason  TEXT,
        applied INTEGER DEFAULT 1
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_watchlist_event_ts ON watchlist_event(ts)",
)


def ensure_schema(conn: sqlite3.Connection) -> None:
    """Create the watchlist tables if absent. Idempotent."""
    for ddl in SCHEMA_DDL:
        conn.execute(ddl)


def _utcnow_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


@dataclass(frozen=True)
class WatchlistEvent:
    """One requested mutation. The only way the list ever changes."""
    action: str
    symbol: str
    source: str
    reason: str = ""
    sleeve_target: str = "quant_core"
    score: float = 0.0
    asset_class: str = ""
    ts: str = ""


def _journal(conn: sqlite3.Connection, ev: WatchlistEvent, ts: str,
             applied: bool) -> None:
    conn.execute(
        "INSERT INTO watchlist_event(ts,action,symbol,source,reason,applied) "
        "VALUES(?,?,?,?,?,?)",
        (ts, ev.action, ev.symbol, ev.source, ev.reason, 1 if applied else 0))


def apply_event(conn: sqlite3.Connection, ev: WatchlistEvent) -> dict:
    """Apply one watchlist event. The single mutation path.

    Returns {"applied": bool, "reason": str}. Every event is journalled whether
    or not it applied, so a refused event from a not-yet-enabled source is
    visible rather than silent.
    """
    ensure_schema(conn)
    ts = ev.ts or _utcnow_iso()

    if ev.action not in VALID_ACTIONS:
        _journal(conn, ev, ts, False)
        return {"applied": False, "reason": "invalid_action"}
    if not ev.symbol:
        _journal(conn, ev, ts, False)
        return {"applied": False, "reason": "no_symbol"}
    if ev.source not in ACTIVE_SOURCES:
        # The seam for the deferred react layer: parsed, journalled, refused.
        _journal(conn, ev, ts, False)
        reason = ("source_not_enabled" if ev.source in RESERVED_SOURCES
                  else "unknown_source")
        return {"applied": False, "reason": reason}

    if ev.action == "add":
        sleeve = (ev.sleeve_target if ev.sleeve_target in VALID_SLEEVES
                  else "quant_core")
        # Re-adding an existing symbol REFRESHES it (updated_ts, reason, score),
        # which is exactly what keeps a live candidate from being pruned as
        # stale. added_ts is preserved, so "when did this first appear" survives.
        conn.execute(
            "INSERT INTO watchlist(symbol,asset_class,added_ts,updated_ts,source,"
            "reason,sleeve_target,score,status,removed_ts,removed_reason) "
            "VALUES(?,?,?,?,?,?,?,?,'active',NULL,NULL) "
            "ON CONFLICT(symbol) DO UPDATE SET "
            "updated_ts=excluded.updated_ts, source=excluded.source, "
            "reason=excluded.reason, sleeve_target=excluded.sleeve_target, "
            "score=excluded.score, status='active', removed_ts=NULL, "
            "removed_reason=NULL, asset_class=excluded.asset_class",
            (ev.symbol, ev.asset_class, ts, ts, ev.source, ev.reason, sleeve,
             float(ev.score or 0.0)))
        _journal(conn, ev, ts, True)
        return {"applied": True, "reason": "added"}

    # remove: soft delete. The row stays so the operator can see what left and
    # why, and so a re-add restores it rather than losing its history.
    cur = conn.execute(
        "UPDATE watchlist SET status='removed', removed_ts=?, removed_reason=?, "
        "updated_ts=? WHERE symbol=? AND status='active'",
        (ts, ev.reason or "removed", ts, ev.symbol))
    applied = cur.rowcount > 0
    _journal(conn, ev, ts, applied)
    return {"applied": applied,
            "reason": "removed" if applied else "not_on_watchlist"}


def add_from_discovery(conn: sqlite3.Connection, symbol: str, *, reason: str,
                       sleeve_target: str = "quant_core", score: float = 0.0,
                       asset_class: str = "", ts: str | None = None) -> dict:
    """Add a Stage-C survivor. The only add path enabled today."""
    return apply_event(conn, WatchlistEvent(
        action="add", symbol=symbol, source="discovery", reason=reason,
        sleeve_target=sleeve_target, score=score, asset_class=asset_class,
        ts=ts or _utcnow_iso()))


def active(conn: sqlite3.Connection) -> list[dict]:
    """Current active watchlist, most recently confirmed first. Read-only."""
    ensure_schema(conn)
    rows = conn.execute(
        "SELECT symbol, asset_class, added_ts, updated_ts, source, reason, "
        "sleeve_target, score, status FROM watchlist WHERE status='active' "
        "ORDER BY updated_ts DESC, symbol ASC").fetchall()
    return [{"symbol": r[0], "asset_class": r[1], "added_ts": r[2],
             "updated_ts": r[3], "source": r[4], "reason": r[5],
             "sleeve_target": r[6], "score": r[7], "status": r[8]} for r in rows]


def active_symbols(conn: sqlite3.Connection,
                   sleeve_target: str | None = None) -> list[str]:
    """Active symbols, optionally for one sleeve. What the engine reads."""
    ensure_schema(conn)
    if sleeve_target:
        rows = conn.execute(
            "SELECT symbol FROM watchlist WHERE status='active' AND "
            "sleeve_target=? ORDER BY symbol", (sleeve_target,)).fetchall()
    else:
        rows = conn.execute(
            "SELECT symbol FROM watchlist WHERE status='active' "
            "ORDER BY symbol").fetchall()
    return [r[0] for r in rows]


def recent_events(conn: sqlite3.Connection, limit: int = 50) -> list[dict]:
    """Recent adds and prunes, so the operator sees the list living."""
    ensure_schema(conn)
    rows = conn.execute(
        "SELECT ts, action, symbol, source, reason, applied FROM watchlist_event "
        "ORDER BY id DESC LIMIT ?", (int(limit),)).fetchall()
    return [{"ts": r[0], "action": r[1], "symbol": r[2], "source": r[3],
             "reason": r[4], "applied": bool(r[5])} for r in rows]


def stale_symbols(conn: sqlite3.Connection, stale_hours: int,
                  now: datetime | None = None) -> list[str]:
    """Active symbols no pass re-confirmed within ``stale_hours``. Pure read."""
    ensure_schema(conn)
    now = now or datetime.now(timezone.utc)
    cutoff = (now - timedelta(hours=max(0, stale_hours))).strftime(
        "%Y-%m-%dT%H:%M:%SZ")
    rows = conn.execute(
        "SELECT symbol FROM watchlist WHERE status='active' AND updated_ts < ? "
        "ORDER BY symbol", (cutoff,)).fetchall()
    return [r[0] for r in rows]


def prune_stale(conn: sqlite3.Connection, stale_hours: int,
                now: datetime | None = None) -> dict:
    """Remove entries whose signal went stale."""
    now = now or datetime.now(timezone.utc)
    ts = now.strftime("%Y-%m-%dT%H:%M:%SZ")
    pruned = []
    for symbol in stale_symbols(conn, stale_hours, now):
        r = apply_event(conn, WatchlistEvent(
            action="remove", symbol=symbol, source="prune",
            reason=f"signal stale, no pass in {stale_hours}h", ts=ts))
        if r["applied"]:
            pruned.append(symbol)
    return {"pruned": pruned, "count": len(pruned)}


def prune_broken_thesis(conn: sqlite3.Connection, symbol: str,
                        reason: str = "thesis invalidated",
                        ts: str | None = None) -> dict:
    """Remove one entry whose thesis broke."""
    return apply_event(conn, WatchlistEvent(
        action="remove", symbol=symbol, source="prune", reason=reason,
        ts=ts or _utcnow_iso()))


def enforce_max_size(conn: sqlite3.Connection, max_size: int,
                     ts: str | None = None) -> dict:
    """Keep the watchlist bounded: drop the lowest-scoring entries past the cap.

    The watchlist is the NARROW end of the funnel. An unbounded list would defeat
    the point, so the cap is enforced on score, keeping the strongest candidates.
    """
    ensure_schema(conn)
    ts = ts or _utcnow_iso()
    rows = conn.execute(
        "SELECT symbol FROM watchlist WHERE status='active' "
        "ORDER BY score DESC, updated_ts DESC, symbol ASC").fetchall()
    overflow = [r[0] for r in rows[max(0, max_size):]]
    dropped = []
    for symbol in overflow:
        r = apply_event(conn, WatchlistEvent(
            action="remove", symbol=symbol, source="prune",
            reason=f"watchlist full (max {max_size}), lower score", ts=ts))
        if r["applied"]:
            dropped.append(symbol)
    return {"dropped": dropped, "count": len(dropped)}
