#!/usr/bin/env python3
"""Load a broad, hindsight-free US equity universe into the analysis database.

Session 2026-07-26. Production market_ai_lab.db stays frozen and is only ever
opened read-only. This script writes ONLY analysis_bars.db, which is
gitignored and rebuildable from this file plus Alpaca credentials.

It answers no strategy question and generates no signal. It loads breadth,
because the capacity-gated round recorded the price-only space as exhausted
against an 8-symbol database and named a new information axis as the only
thing that changes the calculus.

Subcommands:
  probe     pool composition, calendar span, and the projected footprint.
            Writes nothing.
  load      pull the asset list, the trading calendar, and daily bars for the
            whole non-OTC pool. Refuses to write the production path.
  segments  split every loaded series into listing segments and write the
            explicit end marker for dead tickers.
  universe  materialise membership per the hindsight-free rule.
  actions   pull splits and dividends for the loaded universe members.

Every network fact carries the endpoint that produced it.
"""
from __future__ import annotations

import argparse
import collections
import concurrent.futures
import datetime as dt
import json
import os
import sqlite3
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from backtest import universe as U  # noqa: E402
from market_data.alpaca_source import (  # noqa: E402
    _auth_headers, _data_keys, _paper_keys)

DATA_BASE = os.environ.get("ALPACA_DATA_BASE", "https://data.alpaca.markets")
TRADE_BASE = os.environ.get("ALPACA_PAPER_BASE",
                            "https://paper-api.alpaca.markets")
STOCK_BARS = f"{DATA_BASE}/v2/stocks/bars"
CORP_ACTIONS = f"{DATA_BASE}/v1/corporate-actions"
ASSETS = f"{TRADE_BASE}/v2/assets"
CALENDAR = f"{TRADE_BASE}/v2/calendar"

# The pull span. 2016-01-04 is the earliest daily bar Alpaca serves (probed
# on SPY and AAPL), so the start is the source's floor, not a preference. The
# end is frozen at the prior deep-history load's end so both loads describe
# the same market and a rerun is deterministic.
PULL_START = "2016-01-01"
PULL_END = "2026-07-24"

# adjustment=all is split AND dividend. Probed on SPY 2024-03-13: raw and
# split agree at 515.97 while dividend and all agree at 500.84, so the
# dividend leg is real and the two legs compose.
ADJUSTMENT = "all"
EQUITY_FEED = "sip"          # consolidated tape, see VOLUME_SCOPE_NOTE
TIMEFRAME = "1day"
VENUE = "alpaca"
BAR_SOURCE = "backfill"
BATCH_SYMBOLS = 50
PAGE_LIMIT = 10000
PAGE_SLEEP_S = 0.05

PRODUCTION_DB = os.path.join(_ROOT, "market_ai_lab.db")
ANALYSIS_DB_DEFAULT = os.path.join(_ROOT, "analysis_bars.db")

# Corporate-action types are REQUESTED in the singular and ANSWERED under
# plural keys. Verified live 2026-07-26 against /v1/corporate-actions.
CA_TYPES = ("forward_split", "reverse_split", "cash_dividend",
            "stock_dividend", "unit_split")
CA_KEY_TO_KIND = {f"{k}s": k for k in CA_TYPES}

VOLUME_SCOPE_NOTE = (
    "historical equity volume here is CONSOLIDATED (Alpaca SIP), covering "
    "every US venue. The live engine path reads single-venue IEX volume, "
    "which is a small fraction of consolidated. The two are NOT comparable "
    "and any volume-based result from this database must say so.")

SURVIVORSHIP_NOTE = (
    "delisted, acquired, merged, and renamed symbols ARE present: the pool "
    "is Alpaca's active AND inactive us_equity asset lists, and the data API "
    "serves full history for dead tickers up to their last session. Residual "
    "bias is bounded and stated in the validation report: names that left the "
    "listed venues before Alpaca began keeping asset records cannot appear, "
    "and a RENAMED issuer keeps one asset record, so its old ticker's history "
    "can be joined to a later, unrelated listing of the same ticker. Listing "
    "segments detect that and are never joined.")


# ----------------------------------------------------------------- transport

def http_get(url: str, *, trading: bool = False,
             timeout: float = 120.0) -> tuple[int, object]:
    """GET with the HTTP error body captured instead of swallowed."""
    key, secret = _paper_keys() if trading else _data_keys()
    if not key or not secret:
        raise SystemExit("no Alpaca credentials resolvable")
    req = urllib.request.Request(url, headers=_auth_headers(key, secret))
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read()
            return resp.status, json.loads(raw) if raw else {}
    except urllib.error.HTTPError as e:
        return e.code, {"error": (e.read() or b"").decode()[:400]}
    except (urllib.error.URLError, OSError, ValueError, TimeoutError) as e:
        return 0, {"error": str(e)}


def get_with_retry(url: str, *, trading: bool = False,
                   attempts: int = 5) -> tuple[int, object]:
    """One bounded retry ladder for transient failures only.

    429, 5xx, and transport errors are retried with backoff. A 4xx that is
    not 429 is permanent (an invalid symbol stays invalid) and returns at once
    so the caller can act on it instead of waiting out a ladder.
    """
    delay = 1.0
    for attempt in range(attempts):
        code, resp = http_get(url, trading=trading)
        if code == 200:
            return code, resp
        transient = code == 429 or code >= 500 or code == 0
        if not transient or attempt == attempts - 1:
            return code, resp
        time.sleep(delay)
        delay *= 2
    return 0, {"error": "unreachable"}


# -------------------------------------------------------------------- schema

DDL = """
CREATE TABLE IF NOT EXISTS analysis_meta(
  key TEXT PRIMARY KEY, value TEXT NOT NULL);

CREATE TABLE IF NOT EXISTS trading_calendar(
  date TEXT PRIMARY KEY, open TEXT, close TEXT);

CREATE TABLE IF NOT EXISTS universe_asset(
  symbol TEXT PRIMARY KEY,
  asset_id TEXT,
  name TEXT,
  exchange TEXT,
  -- PRESENT-DAY listing status from the asset list. Recorded because it is
  -- the survivorship evidence, never used to decide membership.
  asset_status TEXT,
  is_fund INTEGER,
  -- >1 means the ticker carries more than one asset record, so the bars
  -- endpoint (which keys on symbol) may be serving two listings as one.
  n_asset_ids INTEGER,
  first_bar TEXT, last_bar TEXT, n_bars INTEGER, n_segments INTEGER,
  -- The explicit end marker. 'live' means the series runs to the pull end.
  -- 'ended:<date>' means the ticker stopped trading and is a dead name whose
  -- history stays in the database on purpose.
  end_marker TEXT,
  -- Corporate-action adjustment is computed by the source relative to the
  -- pull date. A split after this date makes the stored series stale.
  adjusted_as_of TEXT,
  adjustment TEXT, feed TEXT, source TEXT, volume_source TEXT,
  loaded_at TEXT,
  -- How name and exchange were obtained, so a classification is auditable.
  classification_source TEXT);

CREATE TABLE IF NOT EXISTS listing_segment(
  symbol TEXT, seg INTEGER, start_date TEXT, end_date TEXT,
  n_bars INTEGER, gap_sessions_before INTEGER,
  PRIMARY KEY(symbol, seg));

CREATE TABLE IF NOT EXISTS corporate_action(
  symbol TEXT, ex_date TEXT, kind TEXT,
  old_rate REAL, new_rate REAL, rate REAL,
  PRIMARY KEY(symbol, ex_date, kind));

-- How a ticker stopped being itself, from the venue's corporate-action
-- record rather than from the absence of bars. This table is the
-- survivorship repair: the asset list DROPS many acquired names (TWTR,
-- SIVB, ATVI, VMW, PXD, HES all return full history from the bars endpoint
-- and appear in no asset list), so the pool cannot be built from the asset
-- list alone without excluding exactly the names that died.
CREATE TABLE IF NOT EXISTS delisting_event(
  symbol TEXT, event_date TEXT, kind TEXT, counterparty TEXT,
  PRIMARY KEY(symbol, event_date, kind));

CREATE TABLE IF NOT EXISTS universe_membership(
  rule TEXT, formation_date TEXT, symbol TEXT, rank INTEGER,
  median_dollar_volume REAL, median_close REAL, window_bars INTEGER,
  PRIMARY KEY(rule, formation_date, symbol));

CREATE TABLE IF NOT EXISTS universe_exclusion(
  stage TEXT, key TEXT, symbol TEXT, reason TEXT, detail TEXT);
"""

INDEX_DDL = """
CREATE INDEX IF NOT EXISTS idx_bars_tf_ts ON bars(timeframe, timestamp);
CREATE INDEX IF NOT EXISTS idx_membership_date
  ON universe_membership(rule, formation_date);
"""


def open_analysis_db(path: str, *, write: bool) -> sqlite3.Connection:
    if write and os.path.abspath(path) == os.path.abspath(PRODUCTION_DB):
        raise SystemExit("refusing to write the production database")
    conn = sqlite3.connect(path)
    if not write:
        return conn
    conn.executescript(DDL)
    _label_prior_adjustment(conn)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=OFF")
    return conn


def _label_prior_adjustment(conn: sqlite3.Connection) -> None:
    """Add the adjustment axis and label the rows that predate it.

    The existing 5-minute rows were pulled with adjustment=split, recorded in
    analysis_meta by the 2026-07-24 loader, and crypto has no corporate
    actions at all. Both labels are DERIVED from what the database already
    records, never guessed: no price changes, only the axis that was missing.
    """
    cols = {r[1] for r in conn.execute("PRAGMA table_info(bars)")}
    if "adjustment" not in cols:
        conn.execute("ALTER TABLE bars ADD COLUMN adjustment TEXT")
    prior = dict(conn.execute("SELECT key, value FROM analysis_meta")).get(
        "equity_adjustment")
    if prior:
        conn.execute("UPDATE bars SET adjustment=? WHERE adjustment IS NULL "
                     "AND timeframe='5min' AND symbol NOT LIKE '%/%'", (prior,))
    conn.execute("UPDATE bars SET adjustment='none' WHERE adjustment IS NULL "
                 "AND symbol LIKE '%/%'")
    conn.commit()


def record_exclusion(conn: sqlite3.Connection, stage: str, key: str,
                     symbol: str, reason: str, detail: str = "") -> None:
    conn.execute("INSERT INTO universe_exclusion(stage,key,symbol,reason,"
                 "detail) VALUES(?,?,?,?,?)", (stage, key, symbol, reason,
                                               detail))


# ------------------------------------------------------------ asset universe

def fetch_assets() -> list[dict]:
    """Both listing statuses. The inactive list is the survivorship fix."""
    out: list[dict] = []
    for status in ("active", "inactive"):
        code, resp = get_with_retry(
            f"{ASSETS}?status={status}&asset_class=us_equity", trading=True)
        if code != 200 or not isinstance(resp, list):
            raise SystemExit(f"asset list {status} failed http={code} {resp}")
        out.extend(resp)
    return out


def pool_from_assets(assets: list[dict]) -> tuple[list[dict], list[tuple]]:
    """The candidate pool, with every drop recorded.

    OTC is dropped because the SIP feed serves it no bars at all: a 60-name
    sample of inactive OTC tickers returned zero bars. That is the source
    refusing, not a liquidity opinion, and no OTC name could reach a
    dollar-volume top 500 anyway.
    """
    ids: dict[str, set] = collections.defaultdict(set)
    inactive: set[str] = set()
    for a in assets:
        ids[a["symbol"]].add(a["id"])
        if a.get("status") == "inactive":
            inactive.add(a["symbol"])
    pool, dropped, seen = [], [], set()
    for a in assets:
        sym = a["symbol"]
        if a.get("exchange") == "OTC":
            dropped.append((sym, "otc_no_sip_bars"))
            continue
        if sym in seen:
            continue
        seen.add(sym)
        pool.append({
            "symbol": sym, "asset_id": a["id"], "name": a.get("name") or "",
            "exchange": a.get("exchange") or "",
            # An inactive record wins when a ticker carries both: the point of
            # the pool is that dead names are present.
            "asset_status": "inactive" if sym in inactive else a.get("status"),
            "n_asset_ids": len(ids[sym]),
        })
    return pool, dropped


def _tri(v: bool | None) -> int | None:
    """Tri-state classification to a nullable column. NULL is unclassified."""
    return None if v is None else int(v)


def fetch_asset(symbol: str) -> dict | None:
    """One asset record by symbol, or None when the venue has none.

    THE LIST ENDPOINT IS NOT THE WHOLE TRUTH. `/v2/assets?status=inactive`
    omits most acquired names, but `/v2/assets/{symbol}` still answers for
    many of them: ATVI, TWTR, VMW, PXD, AMJ and RSX all return 200 here and
    appear in no list. That is why the recovery path can carry metadata at
    all, and why it stored none before this was found.
    """
    code, resp = get_with_retry(
        f"{ASSETS}/{urllib.parse.quote(symbol)}", trading=True)
    return resp if code == 200 and isinstance(resp, dict) else None


def resolve_metadata(symbol: str, renames: dict[str, list[str]],
                     seen: set[str] | None = None, depth: int = 0
                     ) -> tuple[str, str, str] | None:
    """Name and exchange for a symbol, following name changes when needed.

    Only NAME CHANGES are followed, never mergers. A name change is the same
    issuer under a new ticker, so inheriting its classification is sound. A
    merger is a different company, and inheriting an acquirer's type would
    label the acquiree with something it never was.
    """
    seen = seen or set()
    if symbol in seen or depth > 3:
        return None
    seen.add(symbol)
    a = fetch_asset(symbol)
    if a and (a.get("name") or a.get("exchange")):
        return (a.get("name") or "", a.get("exchange") or "",
                "single_lookup" if depth == 0 else f"successor_depth_{depth}")
    for succ in renames.get(symbol, ()):
        got = resolve_metadata(succ, renames, seen, depth + 1)
        if got:
            return got[0], got[1], f"successor:{succ}"
    return None


def cmd_metadata(args) -> dict:
    """Backfill classification metadata and recompute is_fund for every asset.

    Fixes the defect the cross-sectional round found: the recovery path wrote
    an empty name and exchange, `classify_fund` had nothing to inspect, and
    the old bool return admitted the symbol by default. Seven pooled vehicles
    reached the universe that way, one of them an S&P 500 tracker sitting in
    51 of 124 formation books.
    """
    conn = open_analysis_db(args.analysis_db, write=True)
    cols = {r[1] for r in conn.execute("PRAGMA table_info(universe_asset)")}
    if "classification_source" not in cols:
        conn.execute("ALTER TABLE universe_asset ADD COLUMN "
                     "classification_source TEXT")
    renames: dict[str, list[str]] = collections.defaultdict(list)
    for s, cp in conn.execute(
            "SELECT symbol, counterparty FROM delisting_event "
            "WHERE kind='name_changes' AND counterparty IS NOT NULL "
            "AND counterparty != ''"):
        renames[s].append(cp)

    # ONLY SYMBOLS THAT COULD CHANGE MEMBERSHIP ARE LOOKED UP. A symbol
    # enters the universe on a 60-session MEDIAN dollar volume, and the
    # lowest top-500 floor in the whole history is 59.3M USD per day. A
    # median can never exceed the maximum, so a symbol whose single best day
    # is below the threshold cannot reach any top 500 in any window and its
    # classification cannot move a membership row. Everything below stays
    # unclassified, which excludes it, which is the correct default anyway.
    # KEYED ON THE EMPTY NAME, WHICH IS WHAT THE CLASSIFIER READS. Requiring
    # BOTH name and exchange to be empty missed a whole class: the asset list
    # itself returns inactive records carrying an exchange and NO name (RHT,
    # SHPG, ESRX, GGP), which then failed closed as unclassified. Those are
    # acquired operating companies, and excluding them would put back exactly
    # the survivorship bias the breadth load exists to remove.
    todo = [r[0] for r in conn.execute(
        "SELECT a.symbol FROM universe_asset a WHERE COALESCE(a.name,'')='' "
        "AND EXISTS (SELECT 1 FROM bars b "
        "WHERE b.symbol=a.symbol AND b.timeframe=? "
        "AND b.close*b.volume >= ?) ORDER BY a.symbol",
        (TIMEFRAME, args.min_peak_dollar_volume))]
    skipped = conn.execute(
        "SELECT COUNT(*) FROM universe_asset WHERE COALESCE(name,'')=''"
    ).fetchone()[0] - len(todo)
    print(f"  looking up {len(todo)}, skipping {skipped} that cannot reach "
          f"any top 500", flush=True)

    updates: list[tuple] = []
    done = [0]

    def work(sym: str):
        got = resolve_metadata(sym, renames)
        done[0] += 1
        if done[0] % 250 == 0:
            print(f"  {done[0]}/{len(todo)}", flush=True)
        return (sym, got)

    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
        for sym, got in pool.map(work, todo):
            if got:
                updates.append((got[0], got[1], got[2], sym))
    conn.executemany("UPDATE universe_asset SET name=?, exchange=?, "
                     "classification_source=? WHERE symbol=?", updates)
    conn.commit()
    resolved, unresolved = len(updates), len(todo) - len(updates)

    # Recompute is_fund for EVERY asset under the corrected classifier.
    # NULL now means unclassified, which excludes rather than admits.
    rows = conn.execute(
        "SELECT symbol, name, exchange FROM universe_asset").fetchall()
    out = [(None if (v := U.classify_fund(n or "", e or "")) is None
            else int(v), s) for s, n, e in rows]
    conn.executemany("UPDATE universe_asset SET is_fund=? WHERE symbol=?", out)
    conn.execute("UPDATE universe_asset SET classification_source='asset_list'"
                 " WHERE classification_source IS NULL AND "
                 "COALESCE(name,'')||COALESCE(exchange,'') != ''")
    conn.commit()
    counts = dict(conn.execute(
        "SELECT CASE WHEN is_fund IS NULL THEN 'unclassified' "
        "WHEN is_fund=1 THEN 'fund' ELSE 'operating' END, COUNT(*) "
        "FROM universe_asset GROUP BY 1"))
    return {"looked_up": len(todo), "skipped_below_threshold": skipped,
            "resolved": resolved, "unresolved": unresolved,
            "min_peak_dollar_volume": args.min_peak_dollar_volume,
            "classification": counts}


def fetch_calendar() -> list[dict]:
    code, resp = get_with_retry(
        f"{CALENDAR}?start={PULL_START}&end={PULL_END}", trading=True)
    if code != 200 or not isinstance(resp, list):
        raise SystemExit(f"calendar failed http={code} {resp}")
    return resp


# ----------------------------------------------------------------- bars pull

_INVALID_RE = "invalid symbol: "


def _drop_invalid(batch: list[str], body: object) -> str | None:
    """The symbol Alpaca named as invalid, if it named one.

    One bad ticker fails the whole multi-symbol request, so the batch has to
    shed it and retry rather than lose 49 good symbols with it.
    """
    msg = body.get("error", "") if isinstance(body, dict) else ""
    if _INVALID_RE not in msg:
        return None
    bad = msg.split(_INVALID_RE, 1)[1].split('"')[0].split("\\")[0].strip()
    return bad if bad in batch else None


def write_page(conn: sqlite3.Connection, resp: object) -> int:
    """Upsert one page. A bar missing any OHLC field is skipped and recorded,
    never completed with an invented value."""
    from market_data.alpaca_source import BACKFILL_VOLUME_SOURCE

    rows = []
    payload = (resp.get("bars") or {}) if isinstance(resp, dict) else {}
    for sym, bars in payload.items():
        for b in bars or []:
            if any(b.get(k) is None for k in ("t", "o", "h", "l", "c")):
                record_exclusion(conn, "pull", b.get("t", ""), sym,
                                 "incomplete_bar", json.dumps(b)[:200])
                continue
            vol = b.get("v")
            rows.append((VENUE, sym, TIMEFRAME, b["t"], float(b["o"]),
                         float(b["h"]), float(b["l"]), float(b["c"]),
                         float(vol or 0), BAR_SOURCE,
                         BACKFILL_VOLUME_SOURCE if vol is not None
                         else "unknown", ADJUSTMENT))
    if rows:
        conn.executemany(
            "INSERT INTO bars(venue,symbol,timeframe,timestamp,open,high,low,"
            "close,volume,source,volume_source,adjustment) "
            "VALUES(?,?,?,?,?,?,?,?,?,?,?,?) "
            "ON CONFLICT(venue,symbol,timeframe,timestamp) DO UPDATE SET "
            "open=excluded.open, high=excluded.high, low=excluded.low, "
            "close=excluded.close, volume=excluded.volume, "
            "source=excluded.source, volume_source=excluded.volume_source, "
            "adjustment=excluded.adjustment", rows)
        conn.commit()
    return len(rows)


def pull_batch(conn: sqlite3.Connection, batch: list[str]) -> int:
    """Pull one batch's full daily history, shedding invalid tickers.

    A named invalid symbol is dropped and the batch retried. An unattributable
    failure bisects, so one opaque error costs a few extra requests instead of
    the whole batch.
    """
    live = list(batch)
    written = 0
    while live:
        token, shed = None, False
        while True:
            url = (f"{STOCK_BARS}?symbols="
                   f"{urllib.parse.quote(','.join(live), safe=',')}"
                   f"&timeframe=1Day&start={PULL_START}&end={PULL_END}"
                   f"&limit={PAGE_LIMIT}&adjustment={ADJUSTMENT}"
                   f"&feed={EQUITY_FEED}")
            if token:
                url += f"&page_token={urllib.parse.quote(token)}"
            code, resp = get_with_retry(url)
            if code != 200:
                bad = _drop_invalid(live, resp)
                if bad:
                    record_exclusion(conn, "pull", "", bad, "invalid_symbol",
                                     f"http {code}")
                    live.remove(bad)
                    shed = True
                    break
                if len(live) == 1:
                    record_exclusion(conn, "pull", "", live[0], "pull_failed",
                                     f"http {code}")
                    return written
                half = len(live) // 2
                return (written + pull_batch(conn, live[:half])
                        + pull_batch(conn, live[half:]))
            written += write_page(conn, resp)
            token = (resp.get("next_page_token")
                     if isinstance(resp, dict) else None)
            if not token:
                return written
            time.sleep(PAGE_SLEEP_S)
        if not shed:
            return written
    return written


# ------------------------------------------------------------------ commands

def cmd_probe(args) -> dict:
    assets = fetch_assets()
    pool, dropped = pool_from_assets(assets)
    cal = fetch_calendar()
    by_ex = collections.Counter((a.get("exchange"), a.get("status"))
                                for a in assets)
    funds = sum(1 for p in pool
                if U.classify_fund(p["name"], p["exchange"]) is True)
    # Footprint from the measured calibration: 1,406 daily rows per symbol
    # that returns data, 198 bytes per row including index overhead (the byte
    # figure from the existing 652 MB / 3.3M row database).
    rows = len(pool) * 1406
    return {
        "assets_total": len(assets),
        "exchange_status": {f"{k[0]}/{k[1]}": v for k, v in by_ex.most_common()},
        "pool": len(pool),
        "pool_inactive": sum(1 for p in pool if p["asset_status"] == "inactive"),
        "pool_funds": funds,
        "dropped_otc": len(dropped),
        "calendar_sessions": len(cal),
        "calendar_span": [cal[0]["date"], cal[-1]["date"]] if cal else None,
        "projection": {"rows": rows, "gb": round(rows * 198 / 1e9, 2),
                       "requests": round(rows / PAGE_LIMIT),
                       "minutes_at_9144_rows_s": round(rows / 9144 / 60, 1)},
    }


def cmd_load(args) -> dict:
    conn = open_analysis_db(args.analysis_db, write=True)
    loaded_at = dt.datetime.now(dt.timezone.utc).isoformat()
    t0 = time.time()

    cal = fetch_calendar()
    conn.executemany("INSERT OR REPLACE INTO trading_calendar(date,open,close)"
                     " VALUES(?,?,?)",
                     [(d["date"], d.get("open"), d.get("close")) for d in cal])
    pool, dropped = pool_from_assets(fetch_assets())
    conn.execute("DELETE FROM universe_exclusion WHERE stage IN "
                 "('pool','pull')")
    conn.executemany("INSERT INTO universe_exclusion(stage,key,symbol,reason,"
                     "detail) VALUES('pool','',?,?,'')", dropped)
    conn.executemany(
        "INSERT OR REPLACE INTO universe_asset(symbol,asset_id,name,exchange,"
        "asset_status,is_fund,n_asset_ids,adjusted_as_of,adjustment,feed,"
        "source,volume_source,loaded_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",
        [(p["symbol"], p["asset_id"], p["name"], p["exchange"],
          p["asset_status"], _tri(U.classify_fund(p["name"], p["exchange"])),
          p["n_asset_ids"], PULL_END, ADJUSTMENT, EQUITY_FEED, BAR_SOURCE,
          "venue_backfill", loaded_at) for p in pool])
    conn.commit()

    symbols = sorted(p["symbol"] for p in pool)
    if args.limit_symbols:
        symbols = symbols[:args.limit_symbols]
    written = 0
    for i in range(0, len(symbols), BATCH_SYMBOLS):
        written += pull_batch(conn, symbols[i:i + BATCH_SYMBOLS])
        if (i // BATCH_SYMBOLS) % 20 == 0:
            print(f"  {min(i + BATCH_SYMBOLS, len(symbols))}/{len(symbols)} "
                  f"symbols, {written:,} rows, "
                  f"{(time.time() - t0) / 60:.1f} min", flush=True)
    conn.executescript(INDEX_DDL)  # cheapest to build after the bulk load
    meta = {
        "universe_loaded_at": loaded_at,
        "universe_loader": "scripts/breadth_universe_20260726.py",
        "universe_endpoint": STOCK_BARS,
        "universe_assets_endpoint": ASSETS,
        "universe_calendar_endpoint": CALENDAR,
        "universe_feed": EQUITY_FEED,
        "universe_adjustment": ADJUSTMENT,
        "universe_timeframe": TIMEFRAME,
        "universe_pull_start": PULL_START,
        "universe_pull_end": PULL_END,
        "universe_pool_symbols": str(len(symbols)),
        "universe_rows_written": str(written),
        "universe_wall_seconds": str(round(time.time() - t0, 1)),
        "volume_scope_note": VOLUME_SCOPE_NOTE,
        "survivorship_note": SURVIVORSHIP_NOTE,
    }
    conn.executemany("INSERT OR REPLACE INTO analysis_meta(key,value) "
                     "VALUES(?,?)", list(meta.items()))
    conn.commit()
    return {"rows_written": written, "symbols": len(symbols), "meta": meta}


def sessions_of(conn: sqlite3.Connection) -> list[str]:
    return [r[0] for r in conn.execute(
        "SELECT date FROM trading_calendar ORDER BY date")]


def cmd_segments(args) -> dict:
    """Segment every loaded series and write the end markers."""
    conn = open_analysis_db(args.analysis_db, write=True)
    sessions = sessions_of(conn)
    index = {d: i for i, d in enumerate(sessions)}
    last = index[sessions[-1]]
    seg_rows: list[tuple] = []
    asset_rows: list[tuple] = []

    def flush(s: str, ds: list[str]) -> None:
        segs = U.segment_series(ds, index)
        for g in segs:
            seg_rows.append((s, g.index, g.start_date, g.end_date, g.n_bars,
                             g.gap_sessions_before))
        # A series whose last bar is within a segment break of the calendar
        # end is still live; anything earlier is a dead ticker carrying an
        # explicit death date.
        alive = last - index[ds[-1]] <= U.SEGMENT_BREAK_SESSIONS
        asset_rows.append(("live" if alive else f"ended:{ds[-1]}", ds[0],
                           ds[-1], len(ds), len(segs), s))

    sym, dates = None, []
    for s, d in conn.execute(
            "SELECT symbol, substr(timestamp,1,10) d FROM bars "
            "WHERE timeframe=? ORDER BY symbol, d", (TIMEFRAME,)):
        if d not in index:
            continue
        if s != sym:
            if sym is not None and dates:
                flush(sym, dates)
            sym, dates = s, []
        dates.append(d)
    if sym is not None and dates:
        flush(sym, dates)

    conn.execute("DELETE FROM listing_segment")
    conn.executemany("INSERT OR REPLACE INTO listing_segment(symbol,seg,"
                     "start_date,end_date,n_bars,gap_sessions_before) "
                     "VALUES(?,?,?,?,?,?)", seg_rows)
    conn.executemany("UPDATE universe_asset SET end_marker=?, first_bar=?, "
                     "last_bar=?, n_bars=?, n_segments=? WHERE symbol=?",
                     asset_rows)
    conn.commit()
    return {"symbols_with_bars": len(asset_rows), "segments": len(seg_rows),
            "multi_segment": sum(1 for r in asset_rows if r[4] > 1),
            "ended": sum(1 for r in asset_rows if r[0] != "live")}


def _window_candidates(conn: sqlite3.Connection, start: str, end: str,
                       funds: dict, segments: dict) -> list[U.Candidate]:
    """Summarise every symbol's trailing window, streaming one symbol at a
    time so a 15,000-name pool never materialises in memory at once."""
    out: list[U.Candidate] = []
    sym, closes, vols = None, [], []

    def flush() -> None:
        if sym not in funds:
            return
        # PRESERVE THE TRI-STATE. bool(None) is False, so coercing here would
        # put admit-by-default straight back into the membership build after
        # the classifier was fixed to fail closed. NULL stays NULL.
        raw = funds[sym]
        cand = U.summarize_window(
            sym, closes, vols, is_fund=None if raw is None else bool(raw),
            segment_break_in_window=U.has_segment_break_in(
                segments.get(sym, ()), start, end))
        if cand:
            out.append(cand)

    for s, c, v in conn.execute(
            "SELECT symbol, close, volume FROM bars WHERE timeframe=? "
            "AND substr(timestamp,1,10) BETWEEN ? AND ? ORDER BY symbol",
            (TIMEFRAME, start, end)):
        if s != sym:
            if sym is not None:
                flush()
            sym, closes, vols = s, [], []
        closes.append(c)
        vols.append(v)
    if sym is not None:
        flush()
    return out


def cmd_universe(args) -> dict:
    conn = open_analysis_db(args.analysis_db, write=True)
    params = U.RuleParams(top_n=args.top_n, include_funds=args.include_funds)
    sessions = sessions_of(conn)
    funds = dict(conn.execute("SELECT symbol, is_fund FROM universe_asset"))
    segments: dict[str, list[U.Segment]] = collections.defaultdict(list)
    for s, i, a, b, n, g in conn.execute(
            "SELECT symbol,seg,start_date,end_date,n_bars,gap_sessions_before "
            "FROM listing_segment ORDER BY symbol, seg"):
        segments[s].append(U.Segment(i, a, b, n, g))

    conn.execute("DELETE FROM universe_membership WHERE rule=?",
                 (params.rule_id,))
    conn.execute("DELETE FROM universe_exclusion WHERE stage='universe'")
    dates = U.formation_dates(sessions, params)
    total = 0
    for f in dates:
        start, end = U.window_bounds(sessions, f, params.window_sessions)
        members, rejected = U.rank_members(
            _window_candidates(conn, start, end, funds, segments), params)
        conn.executemany(
            "INSERT OR REPLACE INTO universe_membership(rule,formation_date,"
            "symbol,rank,median_dollar_volume,median_close,window_bars) "
            "VALUES(?,?,?,?,?,?,?)",
            [(params.rule_id, f, m.candidate.symbol, m.rank,
              m.candidate.median_dollar_volume, m.candidate.median_close,
              m.candidate.window_bars) for m in members])
        # Rank rejections are the bulk and are summarised, not enumerated:
        # only structurally refused symbols are recorded per symbol, because
        # those are the ones a reader needs to audit.
        conn.executemany(
            "INSERT INTO universe_exclusion(stage,key,symbol,reason,detail) "
            "VALUES('universe',?,?,?,?)",
            [(f, s, r, params.rule_id) for s, r in rejected
             if not r.startswith("below_rank_")])
        total += len(members)
        conn.commit()
    conn.executescript(INDEX_DDL)
    return {"rule": params.rule_id, "formation_dates": len(dates),
            "first": dates[0] if dates else None,
            "last": dates[-1] if dates else None,
            "membership_rows": total}


def cmd_actions(args) -> dict:
    """Splits and dividends for every symbol that is ever a member."""
    conn = open_analysis_db(args.analysis_db, write=True)
    symbols = sorted({r[0] for r in conn.execute(
        "SELECT DISTINCT symbol FROM universe_membership")})
    kinds = CA_TYPES
    written = 0
    for i in range(0, len(symbols), BATCH_SYMBOLS):
        batch = symbols[i:i + BATCH_SYMBOLS]
        token = None
        while True:
            url = (f"{CORP_ACTIONS}?symbols="
                   f"{urllib.parse.quote(','.join(batch), safe=',')}"
                   f"&types={','.join(kinds)}&start={PULL_START}"
                   f"&end={PULL_END}&limit=1000")
            if token:
                url += f"&page_token={urllib.parse.quote(token)}"
            code, resp = get_with_retry(url)
            if code != 200:
                record_exclusion(conn, "actions", "", ",".join(batch)[:80],
                                 "ca_fetch_failed", f"http {code}")
                break
            rows = []
            payload = ((resp.get("corporate_actions") or {})
                       if isinstance(resp, dict) else {})
            for key, items in payload.items():
                # The endpoint answers with PLURAL keys (cash_dividends)
                # while it is asked in the singular (cash_dividend). Store
                # the singular so the stored kind matches the requested one
                # and every reader can name it the same way.
                kind = CA_KEY_TO_KIND.get(key, key)
                for it in items or []:
                    ex = it.get("ex_date") or it.get("process_date")
                    if not ex or not it.get("symbol"):
                        continue
                    rows.append((it["symbol"], ex, kind, it.get("old_rate"),
                                 it.get("new_rate"), it.get("rate")))
            if rows:
                conn.executemany(
                    "INSERT OR REPLACE INTO corporate_action(symbol,ex_date,"
                    "kind,old_rate,new_rate,rate) VALUES(?,?,?,?,?,?)", rows)
                written += len(rows)
            token = (resp.get("next_page_token")
                     if isinstance(resp, dict) else None)
            if not token:
                break
        conn.commit()
        time.sleep(PAGE_SLEEP_S)
    return {"symbols": len(symbols), "actions": written}


# Corporate-action record shapes that END a ticker's life or hand its name to
# a different issuer. Each entry maps the response key to the field naming the
# symbol that stops trading and the field naming the other side.
_DEATH_SHAPES = {
    "cash_mergers": ("acquiree_symbol", None, "effective_date"),
    "stock_mergers": ("acquiree_symbol", "acquirer_symbol", "effective_date"),
    "stock_and_cash_mergers": ("acquiree_symbol", "acquirer_symbol",
                               "effective_date"),
    "name_changes": ("old_symbol", "new_symbol", "process_date"),
    "redemptions": ("symbol", None, "process_date"),
    "worthless_removals": ("symbol", None, "process_date"),
    "reorganizations": ("source_symbol", "new_symbol", "process_date"),
}

# Event types that do NOT end a ticker's life and are deliberately not in
# _DEATH_SHAPES: rights_distributions and partial_calls leave the underlying
# trading, and the split and dividend types are already carried by
# corporate_action. Recorded here so a future reader can see the set was
# decided rather than overlooked.
_NON_DEATH_TYPES = ("rights_distributions", "partial_calls", "spin_offs",
                    "forward_splits", "reverse_splits", "unit_splits",
                    "cash_dividends", "stock_dividends")


def _month_starts(start: str, end: str) -> list[tuple[str, str]]:
    """Month windows covering [start, end], so the sweep pages predictably."""
    out = []
    cur = dt.date.fromisoformat(start).replace(day=1)
    last = dt.date.fromisoformat(end)
    while cur <= last:
        nxt = (cur.replace(day=28) + dt.timedelta(days=4)).replace(day=1)
        out.append((cur.isoformat(),
                    min(nxt - dt.timedelta(days=1), last).isoformat()))
        cur = nxt
    return out


def cmd_recover(args) -> dict:
    """Recover delisted tickers the asset list dropped, from the venue's own
    corporate-action record, and pull their history.

    THIS ONLY EVER ADDS NAMES THAT DIED. It cannot tilt a result optimistic:
    the bias it removes is the one that comes from a universe of survivors.
    A recovered name still has to earn membership through the same rule from
    the same pre-formation bars, so nothing here leaks an outcome.
    """
    conn = open_analysis_db(args.analysis_db, write=True)
    loaded_at = dt.datetime.now(dt.timezone.utc).isoformat()
    seen_types: collections.Counter = collections.Counter()
    events: dict[tuple, tuple] = {}
    windows = _month_starts(PULL_START, PULL_END)
    for i, (a, b) in enumerate(windows):
        token = None
        while True:
            url = (f"{CORP_ACTIONS}?start={a}&end={b}&limit=1000")
            if token:
                url += f"&page_token={urllib.parse.quote(token)}"
            code, resp = get_with_retry(url)
            if code != 200:
                record_exclusion(conn, "recover", a, "", "ca_sweep_failed",
                                 f"http {code}")
                break
            payload = ((resp.get("corporate_actions") or {})
                       if isinstance(resp, dict) else {})
            for key, items in payload.items():
                seen_types[key] += len(items or [])
                shape = _DEATH_SHAPES.get(key)
                if not shape:
                    continue
                sym_f, other_f, date_f = shape
                for it in items or []:
                    sym = it.get(sym_f)
                    day = it.get(date_f) or it.get("process_date")
                    if not sym or not day:
                        continue
                    events[(sym, day, key)] = (
                        sym, day, key, it.get(other_f) if other_f else None)
            token = (resp.get("next_page_token")
                     if isinstance(resp, dict) else None)
            if not token:
                break
        if i % 24 == 0:
            print(f"  swept {a}, {len(events)} death events", flush=True)
    conn.executemany("INSERT OR REPLACE INTO delisting_event(symbol,"
                     "event_date,kind,counterparty) VALUES(?,?,?,?)",
                     list(events.values()))
    conn.commit()

    known = {r[0] for r in conn.execute("SELECT symbol FROM universe_asset")}
    missing = sorted({s for s, _, _ in events} - known)
    # POPULATE THE METADATA THE CLASSIFIER NEEDS. Writing an empty name and
    # exchange here is what let seven pooled vehicles into the universe: the
    # classifier had nothing to inspect and its old bool return admitted them
    # by default. The single-asset endpoint answers for symbols the list
    # endpoint omits, and a name change is followed to its successor when it
    # does not.
    renames: dict[str, list[str]] = collections.defaultdict(list)
    for (sym, day, kind), rec in events.items():
        if kind == "name_changes" and rec[3]:
            renames[sym].append(rec[3])
    rows = []
    for sym in missing:
        got = resolve_metadata(sym, renames)
        nm, ex, src = got if got else ("", "", "unresolved")
        fund = U.classify_fund(nm, ex)
        rows.append((sym, "", nm, ex, "delisted_recovered",
                     None if fund is None else int(fund), 1, PULL_END,
                     ADJUSTMENT, EQUITY_FEED, BAR_SOURCE, "venue_backfill",
                     loaded_at, src))
        time.sleep(0.02)
    conn.executemany(
        "INSERT OR REPLACE INTO universe_asset(symbol,asset_id,name,exchange,"
        "asset_status,is_fund,n_asset_ids,adjusted_as_of,adjustment,feed,"
        "source,volume_source,loaded_at,classification_source) "
        "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)", rows)
    conn.commit()

    written = 0
    for i in range(0, len(missing), BATCH_SYMBOLS):
        written += pull_batch(conn, missing[i:i + BATCH_SYMBOLS])
        if (i // BATCH_SYMBOLS) % 20 == 0:
            print(f"  recovered {min(i + BATCH_SYMBOLS, len(missing))}/"
                  f"{len(missing)}, {written:,} rows", flush=True)
    with_bars = conn.execute(
        "SELECT COUNT(DISTINCT symbol) FROM bars WHERE timeframe=? AND "
        "symbol IN (SELECT symbol FROM universe_asset WHERE "
        "asset_status='delisted_recovered')", (TIMEFRAME,)).fetchone()[0]
    conn.executemany("INSERT OR REPLACE INTO analysis_meta(key,value) "
                     "VALUES(?,?)", [
                         ("universe_recovered_symbols", str(len(missing))),
                         ("universe_recovered_with_bars", str(with_bars)),
                         ("universe_recovered_rows", str(written)),
                         ("universe_ca_types_seen", json.dumps(dict(seen_types))),
                     ])
    conn.commit()
    return {"death_events": len(events), "ca_types_seen": dict(seen_types),
            "symbols_not_in_asset_list": len(missing),
            "recovered_with_bars": with_bars, "rows_written": written}


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("cmd", choices=["probe", "load", "recover", "metadata",
                                    "segments", "universe", "actions"])
    ap.add_argument("--analysis-db", default=ANALYSIS_DB_DEFAULT)
    ap.add_argument("--limit-symbols", type=int, default=0,
                    help="RSS probe / smoke test: pull only the first N")
    ap.add_argument("--top-n", type=int, default=U.TOP_N)
    ap.add_argument("--include-funds", action="store_true")
    ap.add_argument("--min-peak-dollar-volume", type=float, default=10_000_000,
                    help="metadata: skip symbols whose best day is below this, "
                         "since they cannot reach any top 500")
    args = ap.parse_args()
    fn = {"probe": cmd_probe, "load": cmd_load, "recover": cmd_recover,
          "metadata": cmd_metadata, "segments": cmd_segments,
          "universe": cmd_universe, "actions": cmd_actions}[args.cmd]
    print(json.dumps(fn(args), indent=2, default=str))


if __name__ == "__main__":
    main()
