"""Persistence for discovery passes: counts, drops, and Stage-C candidates.

Three tables, all NEW and all discovery-only. Nothing here touches an
operational trading table (trades, positions, events), which the C++ engine
still solely writes. This follows the precedent of market_data/alpaca_source.py
owning ``bars``.

What is stored is the audit trail of the funnel: how many instruments entered,
how many survived each stage, what was dropped and why, what the four levels
concluded about the survivors, and what it cost. That is what makes the
cheap-to-expensive narrowing legible instead of a black box.
"""
from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone

SCHEMA_DDL = (
    """
    CREATE TABLE IF NOT EXISTS discovery_pass (
        id               INTEGER PRIMARY KEY AUTOINCREMENT,
        ts               TEXT NOT NULL,
        asset_class      TEXT NOT NULL,
        universe_count   INTEGER DEFAULT 0,
        finalists_count  INTEGER DEFAULT 0,
        survivors_count  INTEGER DEFAULT 0,
        evaluated_count  INTEGER DEFAULT 0,
        council_calls    INTEGER DEFAULT 0,
        gate_calls       INTEGER DEFAULT 0,
        est_cost_usd     REAL DEFAULT 0,
        budget_remaining INTEGER DEFAULT 0,
        status           TEXT DEFAULT 'ok',
        reason           TEXT,
        whale_surfaced_count INTEGER DEFAULT 0
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_discovery_pass_ts ON discovery_pass(asset_class, ts)",
    """
    CREATE TABLE IF NOT EXISTS discovery_drop (
        id      INTEGER PRIMARY KEY AUTOINCREMENT,
        pass_id INTEGER NOT NULL,
        ts      TEXT NOT NULL,
        symbol  TEXT NOT NULL,
        stage   TEXT NOT NULL,
        reason  TEXT NOT NULL,
        score   REAL DEFAULT 0
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_discovery_drop_pass ON discovery_drop(pass_id)",
    """
    CREATE TABLE IF NOT EXISTS discovery_candidate (
        id            INTEGER PRIMARY KEY AUTOINCREMENT,
        pass_id       INTEGER NOT NULL,
        ts            TEXT NOT NULL,
        symbol        TEXT NOT NULL,
        verdict       TEXT,
        direction     TEXT,
        conviction    REAL DEFAULT 0,
        edge          REAL DEFAULT 0,
        agreement     INTEGER DEFAULT 0,
        size_pct      REAL DEFAULT 0,
        horizon       TEXT,
        sleeve_target TEXT,
        rationale     TEXT,
        whale_surfaced INTEGER DEFAULT 0,
        whale_reason   TEXT,
        extra_json    TEXT
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_discovery_candidate_pass ON discovery_candidate(pass_id)",
)


# Additive migrations for a DB created before a column existed. CREATE TABLE IF
# NOT EXISTS never alters an existing table, so add new columns tolerantly (a
# duplicate-column error on a fresh DB is expected and ignored). Mirrors the C++
# storage.cpp migration pattern. Never destructive.
_MIGRATIONS = (
    "ALTER TABLE discovery_pass ADD COLUMN whale_surfaced_count INTEGER DEFAULT 0",
    "ALTER TABLE discovery_candidate ADD COLUMN whale_surfaced INTEGER DEFAULT 0",
    "ALTER TABLE discovery_candidate ADD COLUMN whale_reason TEXT",
)


def ensure_schema(conn: sqlite3.Connection) -> None:
    """Create the discovery tables if absent, and add new columns. Idempotent."""
    for ddl in SCHEMA_DDL:
        conn.execute(ddl)
    for mig in _MIGRATIONS:
        try:
            conn.execute(mig)
        except sqlite3.OperationalError:
            pass  # duplicate column on a fresh DB: expected


def _utcnow_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _f(v, default: float = 0.0) -> float:
    try:
        return float(v)
    except (TypeError, ValueError):
        return default


def _i(v, default: int = 0) -> int:
    try:
        return int(v)
    except (TypeError, ValueError):
        return default


def record_pass(conn: sqlite3.Connection, result: dict) -> int:
    """Persist one PassResult dict. Returns the new pass_id.

    Takes the plain dict (PassResult.to_dict) rather than the dataclass, so the
    runner, the bridge, and the tests all record through one shape.
    """
    ensure_schema(conn)
    ts = str(result.get("ts") or _utcnow_iso())
    cur = conn.execute(
        "INSERT INTO discovery_pass(ts,asset_class,universe_count,finalists_count,"
        "survivors_count,evaluated_count,council_calls,gate_calls,est_cost_usd,"
        "budget_remaining,status,reason,whale_surfaced_count) "
        "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (ts, str(result.get("asset_class", "")),
         _i(result.get("universe_count")), _i(result.get("finalists_count")),
         _i(result.get("survivors_count")), _i(result.get("evaluated_count")),
         _i(result.get("council_calls")), _i(result.get("gate_calls")),
         _f(result.get("est_cost_usd")), _i(result.get("budget_remaining")),
         str(result.get("status", "ok")), str(result.get("reason", "")),
         _i(result.get("whale_surfaced_count"))))
    pass_id = int(cur.lastrowid or 0)

    for d in result.get("drops", []) or []:
        conn.execute(
            "INSERT INTO discovery_drop(pass_id,ts,symbol,stage,reason,score) "
            "VALUES(?,?,?,?,?,?)",
            (pass_id, ts, str(d.get("symbol", "")), str(d.get("stage", "")),
             str(d.get("reason", "")), _f(d.get("score"))))

    # Only whitelisted fields land in named columns. Anything else goes to
    # extra_json, so a provider payload can never smuggle a raw blob into one.
    known = {"symbol", "verdict", "direction", "conviction", "edge",
             "agreement", "agreement_count", "size_pct", "horizon",
             "sleeve_target", "rationale", "whale_surfaced", "whale_reason",
             "prescreen_score"}
    for c in result.get("candidates", []) or []:
        extra = {k: v for k, v in c.items() if k not in known}
        conn.execute(
            "INSERT INTO discovery_candidate(pass_id,ts,symbol,verdict,direction,"
            "conviction,edge,agreement,size_pct,horizon,sleeve_target,rationale,"
            "whale_surfaced,whale_reason,extra_json) "
            "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (pass_id, ts, str(c.get("symbol", "")), str(c.get("verdict", "")),
             str(c.get("direction", "")), _f(c.get("conviction")),
             _f(c.get("edge")),
             _i(c.get("agreement", c.get("agreement_count"))),
             _f(c.get("size_pct")), str(c.get("horizon", "")),
             str(c.get("sleeve_target", "")), str(c.get("rationale", ""))[:2000],
             1 if c.get("whale_surfaced") else 0,
             str(c.get("whale_reason", "")),
             json.dumps(extra) if extra else None))
    return pass_id


def last_pass_ts(conn: sqlite3.Connection, asset_class: str) -> str | None:
    """ISO ts of the most recent pass for an asset class, else None."""
    ensure_schema(conn)
    row = conn.execute(
        "SELECT ts FROM discovery_pass WHERE asset_class=? "
        "ORDER BY ts DESC, id DESC LIMIT 1", (asset_class,)).fetchone()
    return row[0] if row else None


def council_calls_today(conn: sqlite3.Connection, day: str | None = None) -> int:
    """Discovery council calls used today, across BOTH asset classes.

    The daily discovery budget is shared by crypto and equities, so a busy crypto
    hour correctly leaves fewer calls for the equity pass.
    """
    ensure_schema(conn)
    day = day or datetime.now(timezone.utc).strftime("%Y-%m-%d")
    row = conn.execute(
        "SELECT COALESCE(SUM(council_calls),0) FROM discovery_pass "
        "WHERE substr(ts,1,10)=?", (day,)).fetchone()
    return int(row[0] or 0) if row else 0


def latest_pass(conn: sqlite3.Connection, asset_class: str) -> dict | None:
    """The most recent pass for an asset class, with its drops and candidates."""
    ensure_schema(conn)
    row = conn.execute(
        "SELECT id,ts,asset_class,universe_count,finalists_count,survivors_count,"
        "evaluated_count,council_calls,gate_calls,est_cost_usd,budget_remaining,"
        "status,reason,whale_surfaced_count FROM discovery_pass "
        "WHERE asset_class=? ORDER BY ts DESC, id DESC LIMIT 1",
        (asset_class,)).fetchone()
    if not row:
        return None
    pass_id = row[0]
    drops = conn.execute(
        "SELECT symbol,stage,reason,score FROM discovery_drop WHERE pass_id=? "
        "ORDER BY stage, symbol", (pass_id,)).fetchall()
    cands = conn.execute(
        "SELECT symbol,verdict,direction,conviction,edge,agreement,size_pct,"
        "horizon,sleeve_target,rationale,whale_surfaced,whale_reason "
        "FROM discovery_candidate WHERE pass_id=? ORDER BY conviction DESC",
        (pass_id,)).fetchall()
    return {
        "pass_id": pass_id, "ts": row[1], "asset_class": row[2],
        "universe_count": row[3], "finalists_count": row[4],
        "survivors_count": row[5], "evaluated_count": row[6],
        "council_calls": row[7], "gate_calls": row[8], "est_cost_usd": row[9],
        "budget_remaining": row[10], "status": row[11], "reason": row[12],
        "whale_surfaced_count": row[13],
        "drops": [{"symbol": d[0], "stage": d[1], "reason": d[2], "score": d[3]}
                  for d in drops],
        "candidates": [{"symbol": c[0], "verdict": c[1], "direction": c[2],
                        "conviction": c[3], "edge": c[4], "agreement": c[5],
                        "size_pct": c[6], "horizon": c[7],
                        "sleeve_target": c[8], "rationale": c[9],
                        "whale_surfaced": bool(c[10]), "whale_reason": c[11]}
                       for c in cands],
    }
