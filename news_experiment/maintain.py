"""Resolve what has become resolvable, fill the horizons whose bars arrived.

  python -m news_experiment.maintain --db news_experiment.db

NO COLLECTION, NO PROVIDER CALL, NO JUDGMENT. This entry point exists because
both passes are time-dependent in a way collection is not. A row's scoring
session closes the day after it is collected, and its 10-session companion
horizon closes nine sessions after that, so the work of "fill in what is now
knowable" arrives on a different schedule from the work of "score today's
headlines". Wiring it only into a collection run meant a day the collector
did not run was a day nothing caught up.

IT CANNOT CHANGE A SCORED QUANTITY. `resolve_pending` writes only rows whose
`outcome_state` is `pending`, so a resolved row is never re-priced.
`backfill_horizons` writes only the three unscored companion horizons and only
where they are NULL (`collect.HORIZON_UPDATE_SQL`). Both properties are
structural rather than conventional, and both are mutation-tested.
"""
from __future__ import annotations

import argparse
import json
import os
import sqlite3
import sys
from contextlib import closing

_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _REPO not in sys.path:
    sys.path.insert(0, _REPO)

from . import collect, store  # noqa: E402
from .horizon import Calendar  # noqa: E402

ANALYSIS_DB = os.path.join(_REPO, "analysis_bars.db")


def load_calendar(analysis_db: str) -> Calendar:
    with closing(sqlite3.connect(f"file:{analysis_db}?mode=ro",
                                 uri=True)) as conn:
        return Calendar.from_rows(list(conn.execute(
            "SELECT date, open, close FROM trading_calendar")))


def run_maintenance(db_path: str, analysis_db: str = ANALYSIS_DB) -> dict:
    """Both passes against one database. Returns a report.

    `formation` is left empty in the config on purpose: with no running band
    to seed the cache, every row's band is resolved from the row's OWN
    `formation_date`, which is the behaviour this pass must have.
    """
    cal = load_calendar(analysis_db)
    cfg = collect.RunConfig(formation="", day_from="", day_to="", symbols=0,
                            ceiling=0.0, db_path=db_path,
                            run_kind="maintenance", analysis_db=analysis_db)
    conn = store.open_store(db_path)
    try:
        resolved = collect.resolve_pending(conn, cfg, cal, [])
        conn.commit()
        horizons = collect.backfill_horizons(conn, cfg, cal)
        conn.commit()
    finally:
        conn.close()
    return {"outcomes_resolved": resolved, "horizons": horizons}


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(
        description="Resolve pending outcomes and fill unscored horizons")
    p.add_argument("--db", default=store.DEFAULT_DB)
    p.add_argument("--analysis-db", default=ANALYSIS_DB)
    args = p.parse_args(argv)
    print(json.dumps(run_maintenance(args.db, args.analysis_db), indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
