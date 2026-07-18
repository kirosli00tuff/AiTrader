"""Quarantine the 2026-07-17 walk-substitution contamination by provenance.

The FABLE diagnostic proved live Alpaca data died between 11:50:02Z and
11:55:06Z on 2026-07-17 and the feed ran on the deterministic walk until the
06:55:51Z stop on 2026-07-18. Every 5min bar the engine wrote in that window is
synthetic (SPY drifted 750 to 3081 against a flat real market). Two trades
executed against those prices.

This script marks them, it never deletes: the rows stay visible as evidence
and for the GUI, but carry source='synthetic' / bar_source='synthetic' so the
real-fill gates, training, and any replay exclude them.

The window bars are identified three ways at once, so a real bar cannot be
swept in: the diagnosed time window, the four whitelist symbols, and the
engine-written odd-second timestamp shape (the backfill writes aligned :00
seconds, so its real rows never match).

Idempotent: a second run finds zero rows to mark. Run:
    python scripts/quarantine_synthetic_bars_20260717.py [db_path]
"""
from __future__ import annotations

import json
import sqlite3
import sys

# The diagnosed contamination window (FABLE report, RETURN.md 2026-07-18).
# Last real bar 2026-07-17T11:50:02Z. First walk bar 2026-07-17T11:55:06Z.
# Engine stopped 2026-07-18T06:55:51Z.
WINDOW_START = "2026-07-17T11:55:00Z"
WINDOW_END = "2026-07-18T06:56:00Z"
SYMBOLS = ("BTC/USD", "ETH/USD", "SPY", "QQQ")


def _ensure_columns(conn: sqlite3.Connection) -> None:
    """Tolerant migrations, so the script works on a DB neither side has
    migrated yet. Same statements as storage.cpp and alpaca_source.py."""
    for mig in (
        "ALTER TABLE bars ADD COLUMN source TEXT DEFAULT 'unknown'",
        "ALTER TABLE trades ADD COLUMN bar_source TEXT DEFAULT 'unknown'",
    ):
        try:
            conn.execute(mig)
        except sqlite3.OperationalError:
            pass  # column exists


def quarantine(db_path: str = "market_ai_lab.db") -> dict:
    conn = sqlite3.connect(db_path, timeout=10.0)
    try:
        _ensure_columns(conn)
        ph = ",".join("?" for _ in SYMBOLS)
        # Bars: window + symbol + engine-written shape (odd seconds). Only rows
        # not already marked, so the counts state what THIS run changed.
        bars = conn.execute(
            f"UPDATE bars SET source='synthetic'"
            f" WHERE timeframe='5min'"
            f" AND timestamp >= ? AND timestamp <= ?"
            f" AND symbol IN ({ph})"
            f" AND substr(timestamp, 18, 2) <> '00'"
            f" AND COALESCE(source,'unknown') <> 'synthetic'",
            (WINDOW_START, WINDOW_END, *SYMBOLS)).rowcount
        # Trades: the fills executed inside the window (the diagnosed pair:
        # BTC/USD entry 13:35:10Z at 74,335 walk price, exit 13:50:10Z).
        trades = conn.execute(
            f"UPDATE trades SET bar_source='synthetic'"
            f" WHERE ts >= ? AND ts <= ?"
            f" AND symbol IN ({ph})"
            f" AND mode='paper'"
            f" AND COALESCE(bar_source,'unknown') <> 'synthetic'",
            (WINDOW_START, WINDOW_END, *SYMBOLS)).rowcount
        conn.commit()
        marked_bars_total = conn.execute(
            "SELECT COUNT(*) FROM bars WHERE source='synthetic'"
            " AND timestamp >= ? AND timestamp <= ?",
            (WINDOW_START, WINDOW_END)).fetchone()[0]
        marked_trades_total = conn.execute(
            "SELECT COUNT(*) FROM trades WHERE bar_source='synthetic'"
            " AND ts >= ? AND ts <= ?",
            (WINDOW_START, WINDOW_END)).fetchone()[0]
        return {"db": db_path,
                "window": [WINDOW_START, WINDOW_END],
                "bars_marked_this_run": int(bars),
                "trades_marked_this_run": int(trades),
                "bars_marked_total": int(marked_bars_total),
                "trades_marked_total": int(marked_trades_total)}
    finally:
        conn.close()


if __name__ == "__main__":
    import os
    _repo = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    db = sys.argv[1] if len(sys.argv) > 1 else os.path.join(
        _repo, "market_ai_lab.db")
    print(json.dumps(quarantine(db), indent=2))
