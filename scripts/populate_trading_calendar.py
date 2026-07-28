"""Populate `trading_calendar` forward from the venue's own calendar.

WHY. The calendar ended 2026-07-24 while the collector needs sessions ahead of
today: the horizon convention resolves a headline's first actionable moment at
the NEXT session, and `ret_10session` reaches nine sessions past that. Stage 2
recorded ret_10session at zero of 49 for exactly this reason.

HOW FAR FORWARD. The pre-registration's hard stop is 120 trading days of
collection and the longest recorded horizon reaches 10 sessions past the last
collection day, so 130 sessions is the floor. This script defaults to one year
ahead, which covers it with room.

THE SOURCE IS THE VENUE, NOT A WEEKDAY RULE. Alpaca `/v2/calendar` returns the
real session list with its real open and close per day, so a holiday is absent
rather than guessed and a half day carries its own 13:00 close. A weekday rule
would invent the Friday after Thanksgiving as a full session and get every
horizon crossing it wrong.

WHY THIS IS A SEPARATE SCRIPT. `scripts/breadth_universe_20260726.py` already
writes this table from the SAME endpoint, but only inside its `cmd_load`, which
also rebuilds the symbol pool and deletes `universe_exclusion` rows. Re-running
that to extend a calendar would rebuild a universe as a side effect. This script
touches one table and nothing else.

UPSERT, NEVER DELETE. Existing rows are updated in place and new ones inserted.
History is not rewritten: a session already recorded keeps its identity, and a
changed open or close is a venue correction rather than a fabrication.

  RUN:  .venv/bin/python scripts/populate_trading_calendar.py [--through YYYY-MM-DD]
"""
from __future__ import annotations

import argparse
import json
import os
import sqlite3
import sys
import urllib.request
from contextlib import closing
from datetime import date, timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from account_manager import credentials as cr  # noqa: E402

CALENDAR_URL = "https://paper-api.alpaca.markets/v2/calendar"
DEFAULT_DB = "analysis_bars.db"


def _headers() -> dict[str, str]:
    key = cr.get_credential("alpaca_paper_key")
    secret = cr.get_credential("alpaca_paper_secret")
    if not key or not secret:
        raise SystemExit("REFUSING: no Alpaca paper credentials resolve. A "
                         "trading calendar is not guessable from a weekday "
                         "rule, so there is nothing safe to fall back to.")
    return {"APCA-API-KEY-ID": key, "APCA-API-SECRET-KEY": secret}


def fetch(start: str, end: str) -> list[dict]:
    req = urllib.request.Request(f"{CALENDAR_URL}?start={start}&end={end}",
                                 headers=_headers())
    with urllib.request.urlopen(req, timeout=60) as resp:
        data = json.loads(resp.read())
    if not isinstance(data, list) or not data:
        raise SystemExit(f"REFUSING: venue returned no sessions for "
                         f"{start}..{end}")
    return data


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Populate trading_calendar forward")
    p.add_argument("--db", default=DEFAULT_DB)
    p.add_argument("--from", dest="start", default=None,
                   help="default: the day after the last recorded session")
    p.add_argument("--through", default=None,
                   help="default: one year from today")
    p.add_argument("--dry-run", action="store_true")
    args = p.parse_args(argv)

    with closing(sqlite3.connect(args.db)) as conn:
        lo, hi, n = conn.execute(
            "SELECT MIN(date), MAX(date), COUNT(*) FROM trading_calendar"
        ).fetchone()
        print(f"BEFORE  {lo} .. {hi}   {n} sessions")

        start = args.start or (
            date.fromisoformat(hi) + timedelta(days=1)).isoformat()
        through = args.through or (date.today() + timedelta(days=365)).isoformat()
        if start > through:
            print("nothing to do: the calendar already reaches past the target")
            return 0

        sessions = fetch(start, through)
        print(f"venue returned {len(sessions)} sessions "
              f"{sessions[0]['date']} .. {sessions[-1]['date']}")
        halves = [(s["date"], s["close"]) for s in sessions
                  if s.get("close") != "16:00"]
        print(f"half days in range: {halves or 'none'}")

        if args.dry_run:
            print("DRY RUN, nothing written")
            return 0

        conn.executemany(
            "INSERT INTO trading_calendar(date, open, close) VALUES (?,?,?) "
            "ON CONFLICT(date) DO UPDATE SET open=excluded.open, "
            "close=excluded.close",
            [(s["date"], s.get("open", "09:30"), s.get("close", "16:00"))
             for s in sessions])
        conn.commit()

        lo2, hi2, n2 = conn.execute(
            "SELECT MIN(date), MAX(date), COUNT(*) FROM trading_calendar"
        ).fetchone()
        closes = conn.execute("SELECT close, COUNT(*) FROM trading_calendar "
                              "GROUP BY close ORDER BY 2 DESC").fetchall()
        print(f"AFTER   {lo2} .. {hi2}   {n2} sessions (+{n2 - n})")
        print(f"closes now present: {closes}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
