"""Prune the venue-unserviceable watchlist entries found 2026-07-20.

A live read-only Alpaca probe (2026-07-20, same request shape as the
2026-07-19 session's probe) returned ZERO crypto bars for MANA/USD, RUNE/USD,
ZEC/USD, and APT/USD while UNI/USD got 753 from the same request. Discovery
surfaced all four through Finnhub (which carries them as Binance pairs), the
Alpaca backfill wrote nothing, and they sat active with no real bar history.
The engine fabricated synthetic walk bars for MANA/USD and RUNE/USD, and the
stack-level substitution condition read those as a live substitution: two
unserviceable symbols stopped a stack that was trading six correctly.

This script:
  * removes the four entries through the event-sourced watchlist path
    (apply_event, source "prune"), NEVER a raw DELETE: the SOL/USD postmortem
    documented what a silent DELETE costs, and the soft-deleted rows plus the
    journal stay as evidence,
  * marks any bar of theirs whose provenance is not already non-real as
    'synthetic' (mark, never delete, the quarantine precedent): the venue has
    never served these pairs, so no bar of theirs can be real, and a marked
    bar cannot poison a warm start or a training set.

Serviceability verification in discovery/run.py (2026-07-20) prevents new
entries of this class, and the tradeable invariant contains any that slip in.

Idempotent: a second run finds nothing on the watchlist and no bar to mark.
Run:
    python scripts/prune_unserviceable_20260720.py [db_path]
"""
from __future__ import annotations

import json
import os
import sqlite3
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from discovery import watchlist  # noqa: E402
from market_data.tradeable import REAL_SOURCES  # noqa: E402

# Probed live 2026-07-20: 0 bars each from Alpaca's crypto US feed, from the
# same request that returned 753 UNI/USD bars.
SYMBOLS = ("MANA/USD", "RUNE/USD", "ZEC/USD", "APT/USD")
REASON = ("venue unserviceable: Alpaca has never served a bar for this pair "
          "(probed live 2026-07-20, 0 bars while UNI/USD got 753 in the same "
          "request); symbol_unavailable, pruned")


def prune(db_path: str = "market_ai_lab.db") -> dict:
    conn = sqlite3.connect(db_path, timeout=10.0)
    report: dict = {"db": db_path, "removed": [], "already_gone": [],
                    "bars_marked": {}, "bars_already_non_real": {},
                    "real_bars_found": {}}
    try:
        watchlist.ensure_schema(conn)
        for sym in SYMBOLS:
            # Safety: if the venue HAS served the pair real data by the time
            # this runs, do not touch it. The probe said no; verify anyway.
            real = conn.execute(
                "SELECT COUNT(*) FROM bars WHERE symbol=? AND source IN "
                "(?,?)", (sym, *REAL_SOURCES)).fetchone()[0]
            if real:
                report["real_bars_found"][sym] = real
                continue
            r = watchlist.apply_event(conn, watchlist.WatchlistEvent(
                action="remove", symbol=sym, source="prune", reason=REASON))
            (report["removed"] if r["applied"]
             else report["already_gone"]).append(sym)
            # Mark, never delete: every bar of a never-served pair is
            # fabricated by definition. Most already carry 'synthetic' from
            # the write site; this sweeps any 'unknown' stragglers.
            cur = conn.execute(
                "UPDATE bars SET source='synthetic' WHERE symbol=? AND "
                "source NOT IN (?,?) AND source != 'synthetic'",
                (sym, *REAL_SOURCES))
            report["bars_marked"][sym] = cur.rowcount
            report["bars_already_non_real"][sym] = conn.execute(
                "SELECT COUNT(*) FROM bars WHERE symbol=? AND "
                "source='synthetic'", (sym,)).fetchone()[0]
        conn.commit()
    finally:
        conn.close()
    return report


if __name__ == "__main__":
    db = sys.argv[1] if len(sys.argv) > 1 else "market_ai_lab.db"
    print(json.dumps(prune(db), indent=2))
