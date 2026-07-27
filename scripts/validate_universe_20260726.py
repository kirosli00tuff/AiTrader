#!/usr/bin/env python3
"""Validate the breadth universe before anything is allowed to trust it.

Companion to scripts/breadth_universe_20260726.py. Read-only against
analysis_bars.db and read-only against the production database, which it
hashes to prove the load never touched it.

Nothing here repairs anything. A gap stays a gap, a discontinuity stays a
discontinuity, and both are reported with what is known about their cause.
The 2026-07-26 capacity round found a pandas pad default fabricating signals
inside the 417-day SOL hole, so silent repair is the failure mode this file
exists to make impossible.
"""
from __future__ import annotations

import argparse
import collections
import hashlib
import json
import os
import sqlite3
import sys

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from backtest import universe as U  # noqa: E402

PRODUCTION_DB = os.path.join(_ROOT, "market_ai_lab.db")
ANALYSIS_DB_DEFAULT = os.path.join(_ROOT, "analysis_bars.db")
TIMEFRAME = "1day"

# A cross-sectional study needs enough sessions per name to compute anything
# with a trailing window. Below this a member is loaded but flagged.
MIN_USABLE_BARS = 252
# A corporate action explains a jump when it lands within this many sessions
# of it: an ex-date and the session the adjustment lands on can differ by one,
# and a suspended name can reopen a session or two later.
ACTION_WINDOW_SESSIONS = 3


def _conn(path: str) -> sqlite3.Connection:
    return sqlite3.connect(f"file:{path}?mode=ro", uri=True)


def _sessions(conn: sqlite3.Connection) -> list[str]:
    return [r[0] for r in conn.execute(
        "SELECT date FROM trading_calendar ORDER BY date")]


# ------------------------------------------------------------------ inventory

def inventory(conn: sqlite3.Connection, db_path: str) -> dict:
    row = conn.execute(
        "SELECT COUNT(*), COUNT(DISTINCT symbol), MIN(substr(timestamp,1,10)),"
        " MAX(substr(timestamp,1,10)) FROM bars WHERE timeframe=?",
        (TIMEFRAME,)).fetchone()
    other = dict(conn.execute(
        "SELECT timeframe, COUNT(*) FROM bars GROUP BY timeframe"))
    size = sum(os.path.getsize(db_path + s) for s in ("", "-wal", "-shm")
               if os.path.exists(db_path + s))
    return {
        "daily_rows": row[0], "daily_symbols": row[1],
        "daily_span": [row[2], row[3]],
        "rows_by_timeframe": other,
        "db_bytes": size, "db_gb": round(size / 1e9, 2),
        "adjustment_labels": dict(conn.execute(
            "SELECT COALESCE(adjustment,'NULL'), COUNT(*) FROM bars "
            "GROUP BY 1")),
        "provenance": dict(conn.execute(
            "SELECT source || '/' || COALESCE(volume_source,'NULL'), COUNT(*) "
            "FROM bars WHERE timeframe=? GROUP BY 1", (TIMEFRAME,))),
    }


def calendar_agreement(conn: sqlite3.Connection) -> dict:
    """Every bar date must be a real trading session. A bar on a date the
    exchange was shut is a fabricated date, and would be invisible to any
    check that only counted rows."""
    off = conn.execute(
        "SELECT COUNT(*), COUNT(DISTINCT substr(timestamp,1,10)) FROM bars "
        "WHERE timeframe=? AND substr(timestamp,1,10) NOT IN "
        "(SELECT date FROM trading_calendar)", (TIMEFRAME,)).fetchone()
    sample = [r[0] for r in conn.execute(
        "SELECT DISTINCT substr(timestamp,1,10) FROM bars WHERE timeframe=? "
        "AND substr(timestamp,1,10) NOT IN (SELECT date FROM trading_calendar)"
        " LIMIT 10", (TIMEFRAME,))]
    return {"rows_off_calendar": off[0], "dates_off_calendar": off[1],
            "sample": sample}


def sanity(conn: sqlite3.Connection) -> dict:
    """OHLC relations and value ranges. A violation means the bar is not a
    bar, and it is reported rather than corrected."""
    checks = {
        "high_below_open_or_close":
            "high < open - 1e-9 OR high < close - 1e-9",
        "low_above_open_or_close": "low > open + 1e-9 OR low > close + 1e-9",
        "high_below_low": "high < low - 1e-9",
        "non_positive_close": "close <= 0",
        "negative_volume": "volume < 0",
    }
    out = {}
    for name, pred in checks.items():
        out[name] = conn.execute(
            f"SELECT COUNT(*) FROM bars WHERE timeframe=? AND ({pred})",
            (TIMEFRAME,)).fetchone()[0]
    out["zero_volume_rows"] = conn.execute(
        "SELECT COUNT(*) FROM bars WHERE timeframe=? AND volume = 0",
        (TIMEFRAME,)).fetchone()[0]
    out["fabricated_volume_rows"] = conn.execute(
        "SELECT COUNT(*) FROM bars WHERE timeframe=? AND volume_source IN "
        "('synthetic','fabricated_zeroed')", (TIMEFRAME,)).fetchone()[0]
    return out


# --------------------------------------------------------------- survivorship

def survivorship(conn: sqlite3.Connection) -> dict:
    """Evidence that dead names are actually present, not an assertion."""
    ended = conn.execute(
        "SELECT COUNT(*) FROM universe_asset WHERE end_marker LIKE 'ended:%'"
    ).fetchone()[0]
    live = conn.execute(
        "SELECT COUNT(*) FROM universe_asset WHERE end_marker='live'"
    ).fetchone()[0]
    members = conn.execute(
        "SELECT COUNT(DISTINCT symbol) FROM universe_membership").fetchone()[0]
    dead_members = conn.execute(
        "SELECT COUNT(DISTINCT m.symbol) FROM universe_membership m "
        "JOIN universe_asset a ON a.symbol=m.symbol "
        "WHERE a.end_marker LIKE 'ended:%'").fetchone()[0]
    inactive_members = conn.execute(
        "SELECT COUNT(DISTINCT m.symbol) FROM universe_membership m "
        "JOIN universe_asset a ON a.symbol=m.symbol "
        "WHERE a.asset_status='inactive'").fetchone()[0]
    by_year = dict(conn.execute(
        "SELECT substr(substr(end_marker,7),1,4) yr, COUNT(*) "
        "FROM universe_asset WHERE end_marker LIKE 'ended:%' "
        "AND symbol IN (SELECT symbol FROM universe_membership) "
        "GROUP BY yr ORDER BY yr"))
    # Realized attrition: members at a formation date whose series ends before
    # the next formation date. This is the death rate the universe actually
    # carries, and it is the number to compare against a published base rate.
    deaths = conn.execute(
        "SELECT COUNT(*) FROM universe_membership m JOIN universe_asset a "
        "ON a.symbol=m.symbol WHERE a.end_marker LIKE 'ended:%' "
        "AND substr(a.end_marker,7) >= m.formation_date "
        "AND substr(a.end_marker,7) < date(m.formation_date,'+1 month')"
    ).fetchone()[0]
    slots = conn.execute(
        "SELECT COUNT(*) FROM universe_membership").fetchone()[0]
    months = conn.execute(
        "SELECT COUNT(DISTINCT formation_date) FROM universe_membership"
    ).fetchone()[0]
    return {
        "pool_live": live, "pool_ended": ended,
        "distinct_members_ever": members,
        "members_dead_by_pull_end": dead_members,
        "members_inactive_in_asset_list": inactive_members,
        "member_deaths_by_year": by_year,
        "in_universe_deaths": deaths,
        "member_months": slots,
        "annualised_attrition_pct": (round(deaths / slots * 1200, 2)
                                     if slots else None),
        "formation_months": months,
    }


def ticker_reuse(conn: sqlite3.Connection) -> dict:
    """Symbols whose bar series may cover more than one listing."""
    multi_id = conn.execute(
        "SELECT COUNT(*) FROM universe_asset WHERE n_asset_ids > 1"
    ).fetchone()[0]
    worst = [dict(zip(("symbol", "segments", "first", "last", "bars"), r))
             for r in conn.execute(
        "SELECT symbol, n_segments, first_bar, last_bar, n_bars "
        "FROM universe_asset WHERE n_segments > 1 "
        "ORDER BY n_segments DESC, symbol LIMIT 25")]
    n_multi_seg = conn.execute(
        "SELECT COUNT(*) FROM universe_asset WHERE n_segments > 1"
    ).fetchone()[0]
    reused_members = conn.execute(
        "SELECT COUNT(DISTINCT m.symbol) FROM universe_membership m "
        "JOIN universe_asset a ON a.symbol=m.symbol WHERE a.n_segments > 1"
    ).fetchone()[0]
    return {"symbols_with_multiple_asset_ids": multi_id,
            "symbols_with_multiple_segments": n_multi_seg,
            "members_with_multiple_segments": reused_members,
            "worst": worst}


# --------------------------------------------------------- gaps and continuity

def _member_series(conn: sqlite3.Connection, symbols: set[str]):
    """Stream (symbol, dates, closes) for the given symbols, one at a time."""
    sym, dates, closes = None, [], []
    for s, d, c in conn.execute(
            "SELECT symbol, substr(timestamp,1,10), close FROM bars "
            "WHERE timeframe=? ORDER BY symbol, timestamp", (TIMEFRAME,)):
        if s != sym:
            if sym is not None and sym in symbols:
                yield sym, dates, closes
            sym, dates, closes = s, [], []
        dates.append(d)
        closes.append(c)
    if sym is not None and sym in symbols:
        yield sym, dates, closes


def gaps_and_continuity(conn: sqlite3.Connection) -> dict:
    """Missing bars, gap causes, and every discontinuity with its attribution.

    A gap is the ABSENCE of a row. Nothing is written for a session a symbol
    did not trade, so a gap is distinguishable from a real value by a join
    against trading_calendar and can never be mistaken for a price.
    """
    sessions = _sessions(conn)
    index = {d: i for i, d in enumerate(sessions)}
    members = {r[0] for r in conn.execute(
        "SELECT DISTINCT symbol FROM universe_membership")}
    actions: dict[str, set[int]] = collections.defaultdict(set)
    for sym, ex, kind in conn.execute(
            "SELECT symbol, ex_date, kind FROM corporate_action"):
        if ex in index and kind in ("forward_split", "reverse_split",
                                    "unit_split", "stock_dividend"):
            actions[sym].add(index[ex])
    segs: dict[str, list] = collections.defaultdict(list)
    for s, i, a, b, n, g in conn.execute(
            "SELECT symbol,seg,start_date,end_date,n_bars,gap_sessions_before "
            "FROM listing_segment ORDER BY symbol, seg"):
        segs[s].append(U.Segment(i, a, b, n, g))

    missing_total = missing_syms = 0
    gap_cause: collections.Counter = collections.Counter()
    long_gaps: list[dict] = []
    explained = split_shaped_unexplained = other_unexplained = 0
    worst: list[dict] = []
    thin: list[tuple[str, int]] = []

    for sym, dates, closes in _member_series(conn, members):
        if len(dates) < MIN_USABLE_BARS:
            thin.append((sym, len(dates)))
        # Missing sessions strictly inside each segment: a hole in a listing,
        # not the space between two different listings.
        holed = False
        for seg in segs.get(sym, ()):
            hole = (index[seg.end_date] - index[seg.start_date] + 1
                    - seg.n_bars)
            if hole > 0:
                missing_total += hole
                holed = True
        if holed:
            missing_syms += 1
        for seg in segs.get(sym, ())[1:]:
            cause = ("ticker_reuse_or_relisting"
                     if seg.gap_sessions_before > 60 else "long_halt")
            gap_cause[cause] += 1
            long_gaps.append({"symbol": sym, "resumed": seg.start_date,
                              "gap_sessions": seg.gap_sessions_before,
                              "cause": cause})
        for hit in U.detect_discontinuities(dates, closes):
            near = any(abs(index[hit.date] - a) <= ACTION_WINDOW_SESSIONS
                       for a in actions.get(sym, ()))
            if near:
                explained += 1
            elif U.is_split_shaped(hit.ratio):
                split_shaped_unexplained += 1
                worst.append({"symbol": sym, "date": hit.date,
                              "ratio": round(hit.ratio, 4),
                              "prev_close": hit.prev_close,
                              "close": hit.close,
                              "verdict": "SPLIT-SHAPED, no recorded action"})
            else:
                other_unexplained += 1

    long_gaps.sort(key=lambda g: -g["gap_sessions"])
    return {
        "member_symbols_scanned": len(members),
        "missing_bars_inside_segments": missing_total,
        "symbols_with_missing_bars": missing_syms,
        "long_gap_causes": dict(gap_cause),
        "longest_gaps": long_gaps[:15],
        "discontinuities_explained_by_corporate_action": explained,
        "discontinuities_split_shaped_unexplained": split_shaped_unexplained,
        "discontinuities_other_unexplained": other_unexplained,
        "adjustment_failure_candidates": worst[:20],
        "members_below_min_usable_bars": len(thin),
        "min_usable_bars": MIN_USABLE_BARS,
        "thinnest": sorted(thin, key=lambda t: t[1])[:10],
    }


def split_proofs(conn: sqlite3.Connection) -> list[dict]:
    """Named splits must leave no artificial gap in the stored series."""
    out = []
    for sym, day, ratio in (("NVDA", "2024-06-10", 10.0),
                            ("AAPL", "2020-08-31", 4.0),
                            ("AMZN", "2022-06-06", 20.0),
                            ("GOOGL", "2022-07-18", 20.0),
                            ("TSLA", "2022-08-25", 3.0)):
        before = conn.execute(
            "SELECT substr(timestamp,1,10), close FROM bars WHERE symbol=? "
            "AND timeframe=? AND substr(timestamp,1,10) < ? "
            "ORDER BY timestamp DESC LIMIT 1",
            (sym, TIMEFRAME, day)).fetchone()
        after = conn.execute(
            "SELECT substr(timestamp,1,10), open FROM bars WHERE symbol=? "
            "AND timeframe=? AND substr(timestamp,1,10) >= ? "
            "ORDER BY timestamp ASC LIMIT 1", (sym, TIMEFRAME, day)).fetchone()
        if not before or not after:
            out.append({"symbol": sym, "status": "series does not span it"})
            continue
        gap = after[1] / before[1] - 1.0
        out.append({
            "symbol": sym, "event": f"{ratio:g}-for-1 on {day}",
            "last_close_before": before, "first_open_after": after,
            "gap_pct": round(gap * 100, 2),
            "unadjusted_would_show_pct": round((1.0 / ratio - 1.0) * 100, 2),
            "status": ("adjusted: no artificial gap" if abs(gap) < 0.15
                       else "FAILED: gap looks unadjusted")})
    return out


def dividend_proof(conn: sqlite3.Connection) -> dict:
    """The dividend leg is either applied everywhere or nowhere. Measured by
    comparing a stored close against the raw close the venue would serve."""
    row = conn.execute(
        "SELECT close FROM bars WHERE symbol='SPY' AND timeframe=? AND "
        "substr(timestamp,1,10)='2024-03-13'", (TIMEFRAME,)).fetchone()
    return {
        "spy_2024_03_13_stored": row[0] if row else None,
        "raw_and_split_would_be": 515.97,
        "dividend_and_all_would_be": 500.84,
        "verdict": ("dividend-adjusted" if row and abs(row[0] - 500.84) < 0.5
                    else "NOT dividend-adjusted" if row else "no bar"),
        "endpoint": "https://data.alpaca.markets/v2/stocks/bars"
                    "?symbols=SPY&timeframe=1Day&adjustment={raw|all}&feed=sip",
    }


# ------------------------------------------------------------------- universe

def membership_snapshots(conn: sqlite3.Connection, dates: list[str]) -> dict:
    out = {}
    rule = conn.execute(
        "SELECT rule FROM universe_membership LIMIT 1").fetchone()
    for d in dates:
        rows = conn.execute(
            "SELECT symbol, rank, median_dollar_volume FROM "
            "universe_membership WHERE formation_date=? ORDER BY rank "
            "LIMIT 15", (d,)).fetchall()
        if not rows:
            continue
        n = conn.execute(
            "SELECT COUNT(*), MIN(median_dollar_volume) FROM "
            "universe_membership WHERE formation_date=?", (d,)).fetchone()
        out[d] = {"members": n[0],
                  "floor_median_dollar_volume": round(n[1] or 0),
                  "top15": [(s, r, round(v)) for s, r, v in rows]}
    return {"rule": rule[0] if rule else None, "snapshots": out}


def turnover(conn: sqlite3.Connection) -> dict:
    """How much the universe changes month to month. A rule with no turnover
    is a fixed list wearing a rule's clothes."""
    by_date: dict[str, set] = collections.defaultdict(set)
    for d, s in conn.execute(
            "SELECT formation_date, symbol FROM universe_membership"):
        by_date[d].add(s)
    dates = sorted(by_date)
    rates = []
    for a, b in zip(dates, dates[1:]):
        prev, cur = by_date[a], by_date[b]
        if prev:
            rates.append(len(cur - prev) / len(prev))
    return {"formation_dates": len(dates),
            "mean_monthly_entry_rate_pct":
                round(sum(rates) / len(rates) * 100, 2) if rates else None,
            "max_monthly_entry_rate_pct":
                round(max(rates) * 100, 2) if rates else None}


def exclusions(conn: sqlite3.Connection) -> dict:
    by = dict(conn.execute(
        "SELECT stage || '/' || reason, COUNT(*) FROM universe_exclusion "
        "GROUP BY 1 ORDER BY 2 DESC"))
    uniq = dict(conn.execute(
        "SELECT stage || '/' || reason, COUNT(DISTINCT symbol) FROM "
        "universe_exclusion GROUP BY 1 ORDER BY 2 DESC"))
    return {"rows_by_stage_reason": by,
            "distinct_symbols_by_stage_reason": uniq}


def production_freeze(expect: str | None) -> dict:
    h = hashlib.sha256()
    with open(PRODUCTION_DB, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    prod = _conn(PRODUCTION_DB)
    return {"sha256": h.hexdigest(), "expected": expect,
            "frozen": (h.hexdigest() == expect) if expect else None,
            "rows": {t: prod.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
                     for t in ("bars", "events", "trades", "positions")}}


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--analysis-db", default=ANALYSIS_DB_DEFAULT)
    ap.add_argument("--expect-hash", default=None)
    ap.add_argument("--snapshot-dates",
                    default="2016-07-01,2019-01-02,2020-04-01,2022-01-03,"
                            "2024-01-02,2026-07-01")
    args = ap.parse_args()
    conn = _conn(args.analysis_db)
    report = {
        "inventory": inventory(conn, args.analysis_db),
        "calendar_agreement": calendar_agreement(conn),
        "sanity": sanity(conn),
        "survivorship": survivorship(conn),
        "ticker_reuse": ticker_reuse(conn),
        "corporate_actions": dict(conn.execute(
            "SELECT kind, COUNT(*) FROM corporate_action GROUP BY kind")),
        "split_proofs": split_proofs(conn),
        "dividend_proof": dividend_proof(conn),
        "gaps_and_continuity": gaps_and_continuity(conn),
        "membership": membership_snapshots(conn,
                                           args.snapshot_dates.split(",")),
        "turnover": turnover(conn),
        "exclusions": exclusions(conn),
        "production_freeze": production_freeze(args.expect_hash),
    }
    print(json.dumps(report, indent=2, default=str))


if __name__ == "__main__":
    main()
