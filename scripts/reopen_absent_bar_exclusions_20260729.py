#!/usr/bin/env python3
"""Reopen observations excluded against bars that were simply not loaded yet.

WHAT HAPPENED. `analysis_bars.db` held daily bars only through 2026-07-24 when
the first collection ran on 2026-07-29, because the bars were loaded once by
`scripts/breadth_universe_20260726.py` and nothing on this host refreshed them.
The collector's resolve pass looked up each judged row's scoring session, found
no bar, and recorded `excluded / symbol_did_not_trade`. The symbols traded. The
database did not know. `outcome_state='excluded'` is terminal because the
resolve pass selects only `pending`, so the rows cannot self-heal now that the
bars exist.

WHY REOPENING IS LEGITIMATE AND IS NOT A REPAIR OF A RESULT. The judgment was
recorded BEFORE the outcome was known, and reopening preserves that ordering
exactly: the model's verdict, its strength, its reason, its timestamps and its
prompt hash are all untouched, and no headline is re-sent to any provider. What
failed was DATA AVAILABILITY in our own store, not the experiment's logic, and
`symbol_did_not_trade` names a fact about the market that was not true. The
distinction this project has paid for six times is exactly this one: absence of
evidence is not evidence of absence, and a missing bar is our ignorance rather
than the symbol's silence. Leaving the rows excluded would discard 92 honestly
collected observations to preserve a wrong reason string.

WHAT THIS SCRIPT WILL NOT DO. It does not re-score, does not touch a judgment,
does not query historical news, does not widen its scope past the named session
and reason, and does not reopen a row whose bar is STILL absent. It writes two
columns: `outcome_state` back to `pending` and `exclusion_reason` back to empty.
Resolution itself is left to `python -m news_experiment.maintain`, which is the
same code path every daily run uses.

BAR PRESENCE IS DECIDED BY THE RESOLVER'S OWN PRECONDITION.
`outcomes.price_legs` is the single definition of which bars a row depends on,
so this script cannot disagree with the resolver about what "the bar exists"
means. A hand-rolled second copy of that ternary is how two passes come to
disagree about one row.

  python -m scripts.reopen_absent_bar_exclusions_20260729            # dry run
  python -m scripts.reopen_absent_bar_exclusions_20260729 --apply
"""
from __future__ import annotations

import argparse
import json
import os
import sys

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from news_experiment import collect, outcomes, spec, store  # noqa: E402
from news_experiment.maintain import ANALYSIS_DB, load_calendar  # noqa: E402

TARGET_SESSION = "2026-07-28"


def candidates(conn, session: str) -> list[tuple]:
    """Rows in scope. Narrow by construction: one session, one reason, one
    run kind, and only rows already excluded."""
    return conn.execute(
        "SELECT id, symbol, anchor_kind, anchor_ts, scoring_session, judgment "
        "FROM news_observation "
        "WHERE run_kind='collection' AND query_date=? "
        "AND outcome_state='excluded' AND exclusion_reason=? "
        "ORDER BY id", (session, spec.EXCLUSION_SYMBOL_DID_NOT_TRADE)
    ).fetchall()


def plan(conn, analysis_db: str, session: str) -> dict:
    rows = candidates(conn, session)
    report: dict = {"session": session, "candidates": len(rows),
                    "reopen": [], "leave": []}
    if not rows:
        return report
    cal = load_calendar(analysis_db)
    scoring = sorted({r[4] for r in rows if r[4]})
    if not scoring:
        report["leave"] = [{"id": r[0], "symbol": r[1],
                            "reason": "no scoring session recorded"}
                           for r in rows]
        return report
    # The span comes from the resolver's own helper, so the script cannot
    # disagree with the resolver about which bars a row needs. Deriving it
    # from an offset off the scoring session drops the anchor bar whenever the
    # arithmetic runs off the front of the calendar.
    start = min(collect.needed_days(rows, anchor_idx=3, scoring_idx=4))
    end = cal.session_ahead(scoring[-1], 2) or cal.sessions[-1]
    book = outcomes.PriceBook.load(analysis_db, {r[1] for r in rows},
                                   start, end)
    for rid, sym, kind, anchor_ts, scoring_session, _judgment in rows:
        anchor, close = outcomes.price_legs(book, sym, kind or "",
                                            (anchor_ts or "")[:10],
                                            scoring_session or "")
        if anchor is None or close is None or anchor <= 0:
            missing = []
            if anchor is None or anchor <= 0:
                missing.append("anchor leg")
            if close is None:
                missing.append(f"close for {scoring_session}")
            report["leave"].append({
                "id": rid, "symbol": sym,
                "reason": f"bar still absent ({', '.join(missing)}), stays "
                          f"excluded"})
            continue
        report["reopen"].append({"id": rid, "symbol": sym,
                                 "scoring_session": scoring_session})
    return report


def apply(conn, ids: list[int]) -> int:
    """Reopen to pending and clear the reason. Two columns, nothing else.

    `exclusion_reason` must be cleared here because the resolver's UPDATE
    leaves the column alone when a row resolves cleanly, so a reopened row
    would otherwise carry `symbol_did_not_trade` beside a real price.
    """
    conn.executemany(
        "UPDATE news_observation SET outcome_state='pending', "
        "exclusion_reason=? WHERE id=? AND outcome_state='excluded' "
        "AND exclusion_reason=?",
        [(spec.EXCLUSION_NONE, i, spec.EXCLUSION_SYMBOL_DID_NOT_TRADE)
         for i in ids])
    conn.commit()
    return len(ids)


def state_counts(conn, session: str) -> dict:
    return {state: n for state, n in conn.execute(
        "SELECT outcome_state, COUNT(*) FROM news_observation "
        "WHERE run_kind='collection' AND query_date=? AND state='judged' "
        "GROUP BY outcome_state", (session,))}


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--db", default=store.DEFAULT_DB)
    p.add_argument("--analysis-db", default=ANALYSIS_DB)
    p.add_argument("--session", default=TARGET_SESSION)
    p.add_argument("--apply", action="store_true")
    args = p.parse_args(argv)

    conn = store.open_store(args.db)
    try:
        report = plan(conn, args.analysis_db, args.session)
        report["judged_outcome_states_before"] = state_counts(conn,
                                                             args.session)
        if args.apply and report["reopen"]:
            report["reopened"] = apply(conn, [r["id"]
                                              for r in report["reopen"]])
            report["judged_outcome_states_after"] = state_counts(
                conn, args.session)
        else:
            report["reopened"] = 0
            report["dry_run"] = not args.apply
    finally:
        conn.close()
    print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
