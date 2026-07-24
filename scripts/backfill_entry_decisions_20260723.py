"""One-time backfill of entry_decision rows from historical trade_entry events.

Entry-decision recording (2026-07-23) writes a row per candidate going
forward. This recovers what CAN be recovered for the past: each trade_entry
event becomes one entry_decision row (source='backfill_event') carrying the
values the engine recorded at the time — factor, regime, stop, target,
strength, and the trade's own composed confidence/edge where the trade row is
matchable. NOTHING ELSE IS INVENTED: the per-condition state (RSI-2 value,
ATR band, volume, trend distance) was never recorded and the engine's
in-memory bar window at those moments is not reconstructible byte-for-byte,
so those fields stay absent. Historical REJECTIONS wrote no event at all and
are unrecoverable entirely.

Idempotent: a symbol+ts pair already backfilled is skipped. Follows the dated
one-time-script precedent (quarantine 2026-07-18, prune 2026-07-20).
"""
from __future__ import annotations

import argparse
import json
import os
import sqlite3

_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


_DDL = """
CREATE TABLE IF NOT EXISTS entry_decision (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    ts           TEXT NOT NULL,
    venue        TEXT,
    symbol       TEXT NOT NULL,
    bar_source   TEXT,
    regime       TEXT,
    factor       TEXT,
    outcome      TEXT NOT NULL,
    first_reject TEXT,
    tier         TEXT,
    confidence   REAL,
    edge         REAL,
    trade_id     INTEGER,
    source       TEXT DEFAULT 'live',
    state_json   TEXT
);
CREATE INDEX IF NOT EXISTS idx_entry_decision ON entry_decision(symbol, ts);
"""


def backfill(db_path: str) -> dict:
    conn = sqlite3.connect(db_path, timeout=10.0)
    try:
        # Same DDL as storage/schema.sql (IF NOT EXISTS both sides), so the
        # backfill can run before the engine's next start creates the table.
        conn.executescript(_DDL)
        events = conn.execute(
            "SELECT id, ts, venue, symbol, payload_json FROM events "
            "WHERE kind='trade_entry' ORDER BY id").fetchall()
        written = 0
        skipped = 0
        for _eid, ts, venue, symbol, payload_json in events:
            try:
                payload = json.loads(payload_json or "{}")
            except ValueError:
                payload = {}
            exists = conn.execute(
                "SELECT 1 FROM entry_decision WHERE ts=? AND symbol=? "
                "AND source='backfill_event' LIMIT 1", (ts, symbol)).fetchone()
            if exists:
                skipped += 1
                continue
            trade = conn.execute(
                "SELECT id, combined_conf, combined_edge, bar_source "
                "FROM trades WHERE ts=? AND symbol=? AND outcome IN "
                "('open','win','loss','flat') ORDER BY id LIMIT 1",
                (ts, symbol)).fetchone()
            trade_id = trade[0] if trade else None
            conf = trade[1] if trade else None
            edge = trade[2] if trade else None
            bar_source = trade[3] if trade else None
            state = {k: payload[k] for k in
                     ("factor", "regime", "stop", "target", "strength")
                     if k in payload}
            state["backfill_note"] = (
                "recovered from trade_entry event; per-condition state was "
                "never recorded and is not invented")
            conn.execute(
                "INSERT INTO entry_decision(ts, venue, symbol, bar_source, "
                "regime, factor, outcome, first_reject, tier, confidence, "
                "edge, trade_id, source, state_json) "
                "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (ts, venue or "", symbol, bar_source,
                 str(payload.get("regime", "")), str(payload.get("factor", "")),
                 "entered", "", "", conf, edge, trade_id, "backfill_event",
                 json.dumps(state, sort_keys=True)))
            written += 1
        conn.commit()
        return {"trade_entry_events": len(events), "written": written,
                "skipped_existing": skipped}
    finally:
        conn.close()


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--db", default=os.path.join(_REPO, "market_ai_lab.db"))
    args = ap.parse_args()
    print(json.dumps(backfill(args.db), indent=2))
