"""One-time quarantine of the fabricated live-bar volumes (2026-07-23).

Every real_feed bar closed before the 2026-07-21 fabrication fix carries an
invented volume (a uniform [1000, 10000] draw summed per tick). Those rows no
longer reached the DECISION path while live bars reported absence, but two
consumers still read them: the dollar-volume ranking in discovery/universe.py
(38.9 percent of recent crypto input measured fabricated) and, since live
volume became real again (2026-07-23), the 20-bar trailing average seeded
from history after a restart.

Treatment, per the 2026-07-18 quarantine precedent: MARK, never delete.
  * a `volume_source` column is added (tolerant ALTER),
  * each contaminated row is marked 'fabricated_zeroed',
  * its volume is set to 0, the semantically correct "none reported" — the
    value being replaced is KNOWN fiction, so zeroing removes an invented
    number rather than data. The row, its prices, and its provenance stay.
Every consumer already treats 0 as not-measured, so the mark plus the zero IS
the exclusion the decision path applies.

Scope: rows with source='real_feed' AND volume > 0 AND timestamp < cutoff
(default 2026-07-23T12:00:00Z, hours before the venue-volume feed change
landed, so a post-change real volume can never be swept). Idempotent: marked
rows have volume 0 and never match again.
"""
from __future__ import annotations

import argparse
import json
import os
import sqlite3

_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_CUTOFF = "2026-07-23T12:00:00Z"


def quarantine(db_path: str, cutoff: str = _CUTOFF) -> dict:
    conn = sqlite3.connect(db_path, timeout=10.0)
    try:
        try:
            conn.execute("ALTER TABLE bars ADD COLUMN volume_source TEXT")
        except sqlite3.OperationalError:
            pass  # column exists
        before = conn.execute(
            "SELECT COUNT(*), COALESCE(SUM(close * volume), 0) FROM bars "
            "WHERE source='real_feed' AND volume > 0 AND timestamp < ?",
            (cutoff,)).fetchone()
        conn.execute(
            "UPDATE bars SET volume_source='fabricated_zeroed', volume=0 "
            "WHERE source='real_feed' AND volume > 0 AND timestamp < ?",
            (cutoff,))
        conn.commit()
        marked_total = conn.execute(
            "SELECT COUNT(*) FROM bars WHERE volume_source='fabricated_zeroed'"
        ).fetchone()[0]
        return {"cutoff": cutoff,
                "rows_zeroed_this_run": before[0],
                "fictional_dollar_volume_removed": round(before[1], 2),
                "rows_marked_total": marked_total}
    finally:
        conn.close()


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--db", default=os.path.join(_REPO, "market_ai_lab.db"))
    ap.add_argument("--cutoff", default=_CUTOFF)
    args = ap.parse_args()
    print(json.dumps(quarantine(args.db, args.cutoff), indent=2))
