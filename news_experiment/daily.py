"""The daily collection wrapper. Scheduling only, the collector is untouched.

WHY THIS EXISTS. Collection runs once per completed trading session for about
three months, the specification counts day-clusters, and a session never
collected cannot be recovered without querying historical news, which the
design forbids. A human running the collector by hand for that long WILL leave
a gap. This wrapper makes the daily run mechanical and makes every failure
loud.

WHAT IT DECIDES, all from the trading calendar, never from date arithmetic:

  the target session   the latest session whose FOLLOWING session has closed.
                       Not "yesterday": Monday's run needs Friday, and the day
                       after a Monday holiday still needs Friday. The
                       following-session condition is not pedantry. The
                       collector resolves outcomes at the end of every run,
                       and a judged row whose scoring session has not closed
                       would resolve against absent bars and be excluded
                       forever as `symbol_did_not_trade`. Collecting session T
                       is safe only once T+1 has closed, because T's rows
                       score at T+1's close at the latest.

  the formation date   the latest first-session-of-quarter at or before the
                       target session, from `universe.quarter_formation_dates`.
                       Passing a literal was correct for one quarter and wrong
                       from 2026-10-01 onward. Deriving it re-draws the
                       universe at the boundary with no operator action.

WHAT IT REFUSES:

  a session already collected   the collector is NOT idempotent: it appends
                                one row per symbol-day per run, so running it
                                twice for one session doubles every count.
                                The wrapper refuses instead of the collector
                                changing.
  a run before T+1 closes       see above. Nothing is written, so the session
                                stays collectable later.
  a run whose bars are missing  after the top-up, if the band cannot see
                                bars for T+1, invoking the collector would
                                mis-exclude every judged row. The wrapper
                                aborts BEFORE the collector writes anything.

WHAT IT REPORTS AND NEVER FIXES: gaps. Sessions the calendar says completed
since collection began but which hold no collection rows. Filling one means
querying historical news, so the wrapper names it loudly and moves on.

THE BAR TOP-UP. `analysis_bars.db` daily bars were loaded once by
`scripts/breadth_universe_20260726.py` and end at 2026-07-24. Nothing on this
host refreshed them, which is why the 2026-07-28 session's 92 judged rows all
resolved `symbol_did_not_trade`: the database's ignorance was read as the
symbols' silence. The top-up pulls the band's 1Day bars (same endpoint, feed,
adjustment and provenance tags as the original load) for a trailing window
before every collection, so outcome resolution sees real prices. It re-pulls
about 20 sessions back because `adjustment=all` rewrites history at every
dividend and split, and a window pulled together is internally coherent.

Every run appends one entry to COLLECTION_LOG.md and tees to a rotated log in
`.run/`, success or failure, so no run can end without leaving output.
"""
from __future__ import annotations

import argparse
import json
import os
import sqlite3
import subprocess
import sys
import time
import urllib.parse
import urllib.request
from contextlib import closing
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _REPO not in sys.path:
    sys.path.insert(0, _REPO)

from ops import logpipe  # noqa: E402

from . import spec, store, universe  # noqa: E402
from .horizon import Calendar  # noqa: E402

ANALYSIS_DB = os.path.join(_REPO, "analysis_bars.db")
COLLECTION_LOG = os.path.join(_REPO, "COLLECTION_LOG.md")
LOG_NAME = "news_collect"

# The per-run spend ceiling, USD. Arithmetic: the measured cost is 0.000555
# per call and the one recorded session made 92 calls for 0.051 USD. 1.00
# buys about 1,800 calls, 19.6x the recorded session and 4.5x a session where
# every one of the 400 sampled symbols produced a scored headline. A normal
# session cannot reach it. A runaway (a retry loop, a duplicate storm the
# dedup misses) is bounded at 1.00, and the operator's own first run chose
# the same figure.
DEFAULT_CEILING_USD = 1.00

# Minutes after T+1's close before T is collectable. SIP historical data
# trails real time by 15 minutes, and the daily bar needs to have been cut.
SETTLE_MINUTES = 60

# Sessions re-pulled behind the target. Covers the resolve pass's 2-session
# lookback and keeps the window adjustment-coherent (see module docstring).
TOPUP_TRAILING_SESSIONS = 20

# Below this fraction of band symbols carrying a bar for T+1, the top-up is
# judged failed and the collector is not invoked. Half is deliberately slack:
# genuine halts and delistings exist, a feed failure takes out everything.
MIN_BAR_FRACTION = 0.50

# Above this fraction of judged rows excluded as symbol_did_not_trade, the
# run is flagged: symbols do occasionally not trade, whole samples do not.
MAX_DID_NOT_TRADE_FRACTION = 0.20

STOCK_BARS = (os.environ.get("ALPACA_DATA_BASE", "https://data.alpaca.markets")
              + "/v2/stocks/bars")
BATCH_SYMBOLS = 50
PAGE_SLEEP_S = 0.35

EXIT_OK = 0
EXIT_FAILURE = 1
EXIT_CALENDAR = 2       # the calendar cannot answer
EXIT_PREMATURE = 3      # target derivable but its scoring session is open
EXIT_GAP = 4            # gap detected (collection itself may have succeeded)
EXIT_BARS = 5           # bar top-up insufficient, collector not invoked
EXIT_CEILING = 6        # the collector hit the spend ceiling mid-session


@dataclass
class RunLog:
    """Everything one run learned, written out whatever happens."""
    started_utc: str
    target: str = ""
    formation: str = ""
    gaps: list[str] = field(default_factory=list)
    action: str = ""          # collected | refused_already_present |
                              # refused_premature | refused_bars |
                              # refused_calendar | failed
    detail: str = ""
    rows_before: int | None = None
    rows_after: int | None = None
    spend_usd: float | None = None
    calls: int | None = None
    ceiling_hit: bool = False
    exit_code: int = EXIT_FAILURE


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


class Tee:
    """Print to stdout and append to the rotated run log."""

    def __init__(self, name: str = LOG_NAME):
        os.makedirs(logpipe.run_dir(), exist_ok=True)
        self.path = logpipe.log_path(name)
        logpipe.rotate(self.path)

    def line(self, msg: str) -> None:
        stamp = _now_utc().strftime("%Y-%m-%dT%H:%M:%SZ")
        text = f"[{stamp}] {msg}"
        print(text, flush=True)
        try:
            with open(self.path, "a") as fh:
                fh.write(text + "\n")
        except OSError:
            # The log must never kill the run. stdout still has the line.
            pass


def load_calendar(analysis_db: str) -> Calendar:
    with closing(sqlite3.connect(f"file:{analysis_db}?mode=ro",
                                 uri=True)) as conn:
        rows = list(conn.execute(
            "SELECT date, open, close FROM trading_calendar"))
    return Calendar.from_rows(rows)


def target_session(cal: Calendar, now: datetime,
                   settle_minutes: int = SETTLE_MINUTES
                   ) -> tuple[str | None, str]:
    """The latest session whose following session has closed and settled.

    Returns (session, reason). `session` is None when the calendar cannot
    answer, with `reason` saying why: an empty calendar, a `now` before the
    first collectable moment, or a calendar that has been outrun and holds no
    forward session to verify closure against.
    """
    if not cal.sessions:
        return None, "the trading calendar is empty"
    if len(cal.sessions) < 2:
        return None, "the trading calendar holds fewer than two sessions"
    margin = timedelta(minutes=settle_minutes)
    if cal.close_utc(cal.sessions[-1]) + margin <= now:
        # Even the last known session has closed, so the latest completed
        # session's own successor is unknown. The calendar has been outrun,
        # and collecting would score against sessions it cannot see.
        return None, (f"calendar exhausted: last known session "
                      f"{cal.sessions[-1]} has already closed and nothing "
                      f"follows it to verify the next close against")
    for i in range(len(cal.sessions) - 2, -1, -1):
        t, nxt = cal.sessions[i], cal.sessions[i + 1]
        if cal.close_utc(nxt) + margin <= now:
            return t, ""
    return None, (f"too early: no session's following session has closed "
                  f"{settle_minutes} minutes ago yet (first calendar session "
                  f"{cal.sessions[0]})")


def formation_for(sessions: list[str], target: str) -> str | None:
    """The latest first-session-of-quarter at or before `target` that has a
    full trailing window. None when the calendar cannot supply one."""
    candidates = [d for d in universe.quarter_formation_dates(sessions)
                  if d <= target]
    return candidates[-1] if candidates else None


def collected_sessions(exp_db: str) -> list[str]:
    if not os.path.exists(exp_db):
        return []
    with closing(sqlite3.connect(f"file:{exp_db}?mode=ro", uri=True)) as conn:
        return [r[0] for r in conn.execute(
            "SELECT DISTINCT query_date FROM news_observation "
            "WHERE run_kind='collection' ORDER BY query_date")]


def find_gaps(sessions: list[str], collected: list[str],
              target: str) -> list[str]:
    """Completed sessions since collection began that hold no rows.

    Empty when collection has not begun. The target itself is not a gap, it
    is this run's work.
    """
    if not collected:
        return []
    have = set(collected)
    return [s for s in sessions
            if collected[0] <= s <= target and s != target and s not in have]


def session_rows(exp_db: str, session: str) -> int:
    if not os.path.exists(exp_db):
        return 0
    with closing(sqlite3.connect(f"file:{exp_db}?mode=ro", uri=True)) as conn:
        return conn.execute(
            "SELECT COUNT(*) FROM news_observation "
            "WHERE run_kind='collection' AND query_date=?",
            (session,)).fetchone()[0]


# --------------------------------------------------------------- bar top-up

def _http_get(url: str, timeout: float = 60.0) -> tuple[int, dict]:
    from market_data.alpaca_source import _auth_headers, _data_keys
    key, secret = _data_keys()
    if not key or not secret:
        return 0, {"error": "no Alpaca data credentials resolvable"}
    req = urllib.request.Request(url, headers=_auth_headers(key, secret))
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read()
            return resp.status, json.loads(raw) if raw else {}
    except urllib.error.HTTPError as e:
        return e.code, {"error": (e.read() or b"").decode()[:300]}
    except Exception as e:  # noqa: BLE001
        return 0, {"error": str(e)}


def topup_bars(analysis_db: str, symbols: list[str], start_session: str,
               end_utc: datetime, tee: Tee,
               http_get=_http_get) -> tuple[int, int]:
    """Upsert the band's 1Day bars from `start_session` to now.

    Mirrors the original breadth load exactly: venue alpaca, timeframe 1day,
    feed sip, adjustment all, source backfill, volume_source venue_backfill.
    A bar missing any OHLC field is skipped, never completed. Returns
    (rows_upserted, batches_failed).
    """
    from market_data.alpaca_source import BACKFILL_VOLUME_SOURCE

    start = f"{start_session}T00:00:00Z"
    # Paper-tier SIP refuses windows touching the last 15 minutes (the tick
    # measurement's attempt 2 was blocked by exactly this). Back off 16.
    end = (end_utc - timedelta(minutes=16)).strftime("%Y-%m-%dT%H:%M:%SZ")
    written = 0
    failed_batches = 0
    with closing(sqlite3.connect(analysis_db)) as conn:
        for i in range(0, len(symbols), BATCH_SYMBOLS):
            batch = symbols[i:i + BATCH_SYMBOLS]
            token: str | None = None
            attempts = 0
            while True:
                url = (f"{STOCK_BARS}?symbols="
                       f"{urllib.parse.quote(','.join(batch), safe=',')}"
                       f"&timeframe=1Day&start={start}&end={end}"
                       f"&limit=10000&adjustment=all&feed=sip")
                if token:
                    url += f"&page_token={urllib.parse.quote(token)}"
                code, resp = http_get(url)
                if code != 200:
                    attempts += 1
                    if attempts >= 3:
                        failed_batches += 1
                        tee.line(f"[topup] batch {i // BATCH_SYMBOLS} failed "
                                 f"after {attempts} attempts, http={code} "
                                 f"{str(resp.get('error'))[:120]}")
                        break
                    time.sleep(2.0 * attempts)
                    continue
                rows = []
                for sym, bars in (resp.get("bars") or {}).items():
                    for b in bars or []:
                        if any(b.get(k) is None
                               for k in ("t", "o", "h", "l", "c")):
                            continue
                        vol = b.get("v")
                        rows.append(
                            ("alpaca", sym, "1day", b["t"], float(b["o"]),
                             float(b["h"]), float(b["l"]), float(b["c"]),
                             float(vol or 0), "backfill",
                             BACKFILL_VOLUME_SOURCE if vol is not None
                             else "unknown", "all"))
                if rows:
                    conn.executemany(
                        "INSERT INTO bars(venue,symbol,timeframe,timestamp,"
                        "open,high,low,close,volume,source,volume_source,"
                        "adjustment) VALUES(?,?,?,?,?,?,?,?,?,?,?,?) "
                        "ON CONFLICT(venue,symbol,timeframe,timestamp) "
                        "DO UPDATE SET open=excluded.open, "
                        "high=excluded.high, low=excluded.low, "
                        "close=excluded.close, volume=excluded.volume, "
                        "source=excluded.source, "
                        "volume_source=excluded.volume_source, "
                        "adjustment=excluded.adjustment", rows)
                    conn.commit()
                    written += len(rows)
                token = (resp.get("next_page_token")
                         if isinstance(resp, dict) else None)
                if not token:
                    break
                time.sleep(PAGE_SLEEP_S)
    return written, failed_batches


def bars_present_fraction(analysis_db: str, symbols: list[str],
                          session: str) -> float:
    """The fraction of `symbols` holding a 1day bar dated `session`."""
    if not symbols:
        return 0.0
    with closing(sqlite3.connect(f"file:{analysis_db}?mode=ro",
                                 uri=True)) as conn:
        present = {r[0] for r in conn.execute(
            "SELECT DISTINCT symbol FROM bars WHERE timeframe='1day' "
            "AND timestamp >= ? AND timestamp < ?",
            (f"{session}T00:00:00Z", f"{session}T99"))}
    return sum(1 for s in symbols if s in present) / len(symbols)


# ------------------------------------------------------------- the one run

def append_collection_log(log: RunLog, path: str | None = None) -> None:
    path = path or COLLECTION_LOG
    lines = [
        "",
        f"=== DAILY RUN {log.started_utc} ===",
        f"action:     {log.action or 'failed'}",
        f"target:     {log.target or '(none)'}",
        f"formation:  {log.formation or '(none)'}",
    ]
    if log.gaps:
        lines.append(f"GAP:        {len(log.gaps)} session(s) missing, "
                     f"UNRECOVERABLE by design: {', '.join(log.gaps)}")
    else:
        lines.append("gaps:       none")
    if log.rows_before is not None:
        lines.append(f"rows:       {log.rows_before} before, "
                     f"{log.rows_after} after")
    if log.spend_usd is not None:
        lines.append(f"spend:      {log.spend_usd:.6f} USD over "
                     f"{log.calls} calls")
    if log.ceiling_hit:
        lines.append("CEILING HIT: the run stopped mid-session, the session "
                     "is PARTIAL, operator decision required")
    if log.detail:
        lines.append(f"detail:     {log.detail}")
    lines.append(f"exit:       {log.exit_code}")
    with open(path, "a") as fh:
        fh.write("\n".join(lines) + "\n")


def run_collector(target: str, formation: str, ceiling: float, exp_db: str,
                  analysis_db: str, tee: Tee) -> tuple[int, dict | None]:
    """Invoke the collector through its own CLI, attestation flag included,
    so the blessed argument path stays the only entry point."""
    argv = [sys.executable, "-m", "news_experiment.collect",
            "--formation", formation, "--from", target, "--to", target,
            "--ceiling", f"{ceiling:.2f}", "--db", exp_db,
            "--analysis-db", analysis_db, "--run-kind", "collection",
            "--i-have-read-the-preconditions"]
    tee.line(f"[collector] {' '.join(argv[1:])}")
    proc = subprocess.run(argv, capture_output=True, text=True, cwd=_REPO)
    for stream in (proc.stdout, proc.stderr):
        for line in (stream or "").splitlines():
            tee.line(f"[collector] {line}")
    report = None
    idx = (proc.stdout or "").rfind("\n{")
    if idx >= 0:
        try:
            report = json.loads(proc.stdout[idx:])
        except json.JSONDecodeError:
            report = None
    return proc.returncode, report


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(
        description="Daily news-collection wrapper (scheduling only)")
    p.add_argument("--db", default=store.DEFAULT_DB)
    p.add_argument("--analysis-db", default=ANALYSIS_DB)
    p.add_argument("--ceiling", type=float, default=DEFAULT_CEILING_USD)
    p.add_argument("--settle-minutes", type=int, default=SETTLE_MINUTES)
    args = p.parse_args(argv)

    now = _now_utc()
    tee = Tee()
    log = RunLog(started_utc=now.strftime("%Y-%m-%dT%H:%M:%SZ"))
    try:
        code = _run(args, now, tee, log)
    except Exception as exc:  # noqa: BLE001
        log.action = "failed"
        log.detail = f"unhandled: {type(exc).__name__}: {exc}"
        tee.line(f"FAILED: {log.detail}")
        code = EXIT_FAILURE
    log.exit_code = code
    try:
        append_collection_log(log)
    except OSError as exc:
        tee.line(f"could not append COLLECTION_LOG.md: {exc}")
        code = code or EXIT_FAILURE
    tee.line(f"exit {code} ({log.action or 'failed'})")
    return code


def _run(args, now: datetime, tee: Tee, log: RunLog) -> int:
    today_et = now.astimezone(ZoneInfo(spec.MARKET_TZ)).strftime("%Y-%m-%d")
    tee.line(f"run at {log.started_utc} (ET date {today_et})")

    cal = load_calendar(args.analysis_db)
    if today_et not in cal.closes:
        tee.line(f"{today_et} is not a trading session. The target is "
                 f"derived from the calendar either way.")

    target, why = target_session(cal, now, args.settle_minutes)
    if target is None:
        log.action = ("refused_calendar" if "exhaust" in why or "empty" in why
                      or "fewer" in why else "refused_premature")
        log.detail = why
        tee.line(f"REFUSING: {why}")
        return (EXIT_CALENDAR if log.action == "refused_calendar"
                else EXIT_PREMATURE)
    log.target = target
    nxt = cal.next_session(target)
    tee.line(f"target session {target} (its scoring session {nxt} closed "
             f"{cal.close_utc(nxt).strftime('%Y-%m-%dT%H:%M:%SZ')})")

    formation = formation_for(list(cal.sessions), target)
    if formation is None:
        log.action = "refused_calendar"
        log.detail = f"no quarter formation date at or before {target}"
        tee.line(f"REFUSING: {log.detail}")
        return EXIT_CALENDAR
    log.formation = formation
    tee.line(f"formation date {formation} (first session of the quarter, "
             f"derived, not passed)")

    collected = collected_sessions(args.db)
    log.gaps = find_gaps(list(cal.sessions), collected, target)
    for g in log.gaps:
        tee.line(f"GAP: session {g} completed and holds no collection rows. "
                 f"UNRECOVERABLE by design (filling it would query "
                 f"historical news). Recorded, not filled.")

    log.rows_before = session_rows(args.db, target)
    if target in collected:
        log.action = "refused_already_present"
        log.rows_after = log.rows_before
        log.detail = (f"{log.rows_before} rows already recorded for {target}, "
                      f"the collector is append-only, re-running would "
                      f"double-count")
        tee.line(f"IDEMPOTENT REFUSAL: {log.detail}")
        return EXIT_GAP if log.gaps else EXIT_OK

    tee.line(f"[universe] resolving band at formation {formation} for the "
             f"bar top-up symbol list")
    sessions = list(cal.sessions)
    members, _rejects = universe.resolve_band(args.analysis_db, formation,
                                              sessions=sessions)
    symbols = [m.symbol for m in members]
    t_idx = sessions.index(target)
    start_session = sessions[max(0, t_idx - TOPUP_TRAILING_SESSIONS)]
    # NEVER re-pull bars dated before the formation date. adjustment=all
    # re-baselines the whole history at every later dividend, so touching
    # formation-window bars could flip borderline symbols in or out of the
    # band mid-quarter. Membership is point-in-time only while the bars it
    # was decided from stay untouched.
    start_session = max(start_session, formation)
    tee.line(f"[topup] {len(symbols)} band symbols, 1Day bars "
             f"{start_session}..now, feed sip, adjustment all")
    written, failed = topup_bars(args.analysis_db, symbols, start_session,
                                 now, tee)
    tee.line(f"[topup] {written} bars upserted, {failed} failed batches")

    frac = bars_present_fraction(args.analysis_db, symbols, nxt)
    tee.line(f"[topup] {frac:.1%} of band symbols hold a bar for the scoring "
             f"session {nxt} (floor {MIN_BAR_FRACTION:.0%})")
    if frac < MIN_BAR_FRACTION:
        log.action = "refused_bars"
        log.detail = (f"only {frac:.1%} of the band holds a bar for {nxt}, "
                      f"resolving now would mis-exclude judged rows as "
                      f"symbol_did_not_trade. Nothing was written, {target} "
                      f"stays collectable.")
        tee.line(f"REFUSING: {log.detail}")
        return EXIT_BARS

    rc, report = run_collector(target, formation, args.ceiling, args.db,
                               args.analysis_db, tee)
    log.rows_after = session_rows(args.db, target)
    if rc != 0 or report is None:
        log.action = "failed"
        log.detail = (f"collector exit {rc}, report "
                      f"{'parsed' if report else 'missing'}")
        tee.line(f"FAILED: {log.detail}")
        return EXIT_FAILURE

    log.action = "collected"
    log.spend_usd = report.get("spend_usd")
    log.calls = report.get("calls")
    log.ceiling_hit = bool(report.get("ceiling_hit"))
    tee.line(f"collected {target}: {log.rows_after - log.rows_before} rows, "
             f"{log.calls} calls, {log.spend_usd} USD")
    if log.ceiling_hit:
        log.detail = (f"spend ceiling {args.ceiling:.2f} USD hit mid-run, "
                      f"{target} is PARTIAL. The wrapper will refuse this "
                      f"session tomorrow (rows exist), so re-collection is an "
                      f"operator decision, not an automatic retry.")
        tee.line(f"CEILING HIT: {log.detail}")
        return EXIT_CEILING

    with closing(sqlite3.connect(f"file:{args.db}?mode=ro",
                                 uri=True)) as conn:
        judged, dnt = conn.execute(
            "SELECT COUNT(*), SUM(CASE WHEN exclusion_reason="
            "'symbol_did_not_trade' THEN 1 ELSE 0 END) "
            "FROM news_observation WHERE run_kind='collection' "
            "AND query_date=? AND state='judged'", (target,)).fetchone()
    dnt = dnt or 0
    if judged and dnt / judged > MAX_DID_NOT_TRADE_FRACTION:
        log.detail = (f"{dnt} of {judged} judged rows excluded as "
                      f"symbol_did_not_trade. Symbols do halt, whole samples "
                      f"do not: this is the bar-feed failure signature.")
        tee.line(f"ANOMALY: {log.detail}")
        return EXIT_BARS

    return EXIT_GAP if log.gaps else EXIT_OK


if __name__ == "__main__":
    raise SystemExit(main())
