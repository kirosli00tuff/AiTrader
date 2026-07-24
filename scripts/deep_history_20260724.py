#!/usr/bin/env python3
"""Deep-history probe, load, and validation for the analysis database.

Session 2026-07-24. Production market_ai_lab.db stays frozen. This script
reads Alpaca and writes ONLY the separate analysis database the harness can
be pointed at with --db. It asks no strategy question.

Subcommands:
  probe     report the earliest served 5-minute bar per core symbol, feed
            entitlement, adjustment parameter behavior, and the projected
            pull size. Pulls nothing.
  load      pull the stated spans into the analysis database with
            provenance tags. Refuses to write to the production path.
  validate  split proofs, per-symbol per-year gaps and volume presence,
            usable counts, and the production freeze check.

Every network fact in the reports carries the endpoint that produced it.
"""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
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

from market_data.alpaca_source import _auth_headers, _data_keys  # noqa: E402

DATA_BASE = os.environ.get("ALPACA_DATA_BASE", "https://data.alpaca.markets")
STOCK_BARS = f"{DATA_BASE}/v2/stocks/bars"
CRYPTO_BARS = f"{DATA_BASE}/v1beta3/crypto/us/bars"
STOCK_LATEST = f"{DATA_BASE}/v2/stocks/bars/latest"

EQUITIES = ["SPY", "QQQ", "AAPL", "MSFT", "NVDA"]
CRYPTO = ["BTC/USD", "ETH/USD", "SOL/USD"]

# Pull span choices, stated before pulling. Equities start 2019-01-01 so the
# span covers the COVID crash, the 2020-08-31 AAPL split, the 2021 bull, the
# 2022 bear, the 2023-2024 bull, and the 2024-06-10 NVDA split. Crypto starts
# at whatever Alpaca genuinely serves. The end is frozen at the session date
# so reruns are deterministic and the SIP 15-minute recency rule never bites.
EQUITY_START = "2019-01-01T00:00:00Z"
CRYPTO_START = "2015-01-01T00:00:00Z"
PULL_END = "2026-07-24T00:00:00Z"

# Known corporate actions the loaded series must prove adjusted.
SPLIT_EVENTS = [
    {"symbol": "NVDA", "date": "2024-06-10", "ratio": 10.0},
    {"symbol": "AAPL", "date": "2020-08-31", "ratio": 4.0},
]

PRODUCTION_DB = os.path.join(_ROOT, "market_ai_lab.db")
ANALYSIS_DB_DEFAULT = os.path.join(_ROOT, "analysis_bars.db")
PAGE_SLEEP_S = 0.35
BYTES_PER_ROW_EST = 130  # sqlite row incl. index overhead, from production


def http_get(url: str, timeout: float = 30.0) -> tuple[int, dict]:
    """GET with the HTTP error body captured instead of swallowed."""
    key, secret = _data_keys()
    if not key or not secret:
        raise SystemExit("no Alpaca data credentials resolvable")
    req = urllib.request.Request(url, headers=_auth_headers(key, secret))
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read()
            return resp.status, json.loads(raw) if raw else {}
    except urllib.error.HTTPError as e:
        return e.code, {"error": (e.read() or b"").decode()[:300]}
    except (urllib.error.URLError, OSError, ValueError, TimeoutError) as e:
        return 0, {"error": str(e)}


def bars_url(base: str, symbols: list[str], start: str, end: str | None,
             limit: int, extra: str = "", page_token: str | None = None) -> str:
    q = urllib.parse.quote(",".join(symbols), safe=",")
    url = f"{base}?symbols={q}&timeframe=5Min&start={start}&limit={limit}"
    if end:
        url += f"&end={end}"
    if extra:
        url += extra
    if page_token:
        url += f"&page_token={urllib.parse.quote(page_token)}"
    return url


def earliest_bar(base: str, symbol: str, start: str, extra: str = "") -> dict:
    url = bars_url(base, [symbol], start, None, 1, extra)
    code, resp = http_get(url)
    bars = (resp.get("bars") or {}).get(symbol) or []
    return {"symbol": symbol, "endpoint": url, "http": code,
            "earliest": bars[0]["t"] if bars else None,
            "error": resp.get("error")}


def day_bar_count(base: str, symbol: str, day: str, extra: str = "") -> int:
    url = bars_url(base, [symbol], f"{day}T00:00:00Z", f"{day}T23:59:59Z",
                   10000, extra)
    _, resp = http_get(url)
    return len((resp.get("bars") or {}).get(symbol) or [])


def probe() -> dict:
    """Task 1 to 3 network probes. Pulls nothing."""
    out: dict = {"probed_at": dt.datetime.now(dt.timezone.utc).isoformat(),
                 "equities": [], "crypto": []}

    for sym in EQUITIES:
        row = earliest_bar(STOCK_BARS, sym, "2015-01-01T00:00:00Z",
                           "&adjustment=raw&feed=sip")
        row["feed"] = "sip"
        out["equities"].append(row)
    for sym in CRYPTO:
        out["crypto"].append(earliest_bar(CRYPTO_BARS, sym, CRYPTO_START))

    # Feed entitlement and volume scale: the same recent hour on SIP vs IEX.
    probe_day = "2026-07-22"
    feed_cmp = {}
    for feed in ("sip", "iex"):
        url = bars_url(STOCK_BARS, ["SPY"], f"{probe_day}T14:00:00Z",
                       f"{probe_day}T15:00:00Z", 10000,
                       f"&adjustment=raw&feed={feed}")
        code, resp = http_get(url)
        bars = (resp.get("bars") or {}).get("SPY") or []
        feed_cmp[feed] = {"endpoint": url, "http": code, "bars": len(bars),
                          "sum_volume": sum(b.get("v", 0) for b in bars),
                          "error": resp.get("error")}
    out["feed_comparison_spy_hour"] = feed_cmp

    # Live-path feed identity: what does the latest-bar endpoint serve by
    # default. The engine's live volume path (P16) calls this endpoint with
    # no feed parameter.
    live = {}
    for label, extra in (("default", ""), ("iex", "&feed=iex"),
                         ("sip", "&feed=sip")):
        url = f"{STOCK_LATEST}?symbols=SPY{extra}"
        code, resp = http_get(url)
        bar = (resp.get("bars") or {}).get("SPY") or {}
        live[label] = {"endpoint": url, "http": code,
                       "t": bar.get("t"), "v": bar.get("v"),
                       "error": resp.get("error")}
    out["latest_bar_feed_identity"] = live

    # Adjustment parameter behavior on the known NVDA split, daily bars,
    # raw vs split. Proves the parameter does something before the big pull.
    adj = {}
    for adjustment in ("raw", "split"):
        q = urllib.parse.quote("NVDA")
        url = (f"{STOCK_BARS}?symbols={q}&timeframe=1Day"
               f"&start=2024-06-05T00:00:00Z&end=2024-06-11T23:59:59Z"
               f"&limit=10&adjustment={adjustment}&feed=sip")
        code, resp = http_get(url)
        bars = (resp.get("bars") or {}).get("NVDA") or []
        adj[adjustment] = {"endpoint": url, "http": code,
                           "closes": {b["t"][:10]: b["c"] for b in bars},
                           "error": resp.get("error")}
    out["adjustment_probe_nvda_split"] = adj

    # Projection before pulling: measured bars per day times projected days.
    eq_bars_day = day_bar_count(STOCK_BARS, "SPY", probe_day,
                                "&adjustment=split&feed=sip")
    cr_bars_day = day_bar_count(CRYPTO_BARS, "BTC/USD", probe_day)
    projection = {"equity_bars_per_session_measured": eq_bars_day,
                  "crypto_bars_per_day_measured": cr_bars_day, "symbols": {}}
    end_d = dt.date.fromisoformat(PULL_END[:10])
    total_rows = 0
    for row in out["equities"]:
        if not row["earliest"]:
            continue
        start_d = max(dt.date.fromisoformat(row["earliest"][:10]),
                      dt.date.fromisoformat(EQUITY_START[:10]))
        sessions = sum(1 for i in range((end_d - start_d).days)
                       if (start_d + dt.timedelta(days=i)).weekday() < 5)
        n = sessions * eq_bars_day
        projection["symbols"][row["symbol"]] = {
            "pull_start": max(row["earliest"], EQUITY_START),
            "pull_end": PULL_END, "projected_bars": n}
        total_rows += n
    for row in out["crypto"]:
        if not row["earliest"]:
            continue
        start_d = dt.date.fromisoformat(row["earliest"][:10])
        n = (end_d - start_d).days * cr_bars_day
        projection["symbols"][row["symbol"]] = {
            "pull_start": row["earliest"], "pull_end": PULL_END,
            "projected_bars": n}
        total_rows += n
    projection["projected_total_rows"] = total_rows
    projection["projected_storage_mb"] = round(
        total_rows * BYTES_PER_ROW_EST / 1e6)
    out["projection"] = projection
    return out


def make_analysis_db(path: str) -> sqlite3.Connection:
    conn = sqlite3.connect(path)
    with open(os.path.join(_ROOT, "storage", "schema.sql")) as fh:
        conn.executescript(fh.read())
    # Provenance columns land via runtime ALTER in production; mirror them.
    for ddl in ("ALTER TABLE bars ADD COLUMN source TEXT DEFAULT 'unknown'",
                "ALTER TABLE bars ADD COLUMN volume_source TEXT"):
        try:
            conn.execute(ddl)
        except sqlite3.OperationalError:
            pass
    conn.execute("CREATE TABLE IF NOT EXISTS analysis_meta"
                 "(key TEXT PRIMARY KEY, value TEXT NOT NULL)")
    return conn


def pull_symbols(conn: sqlite3.Connection, base: str, symbols: list[str],
                 start: str, extra: str) -> dict[str, int]:
    """Paginate one multi-symbol pull into the bars table. Upsert mirrors
    market_data.alpaca_source._upsert_bars: venue alpaca, timeframe 5min,
    source backfill, raw Alpaca timestamps."""
    written = {s: 0 for s in symbols}
    page_token: str | None = None
    for page in range(3000):
        url = bars_url(base, symbols, start, PULL_END, 10000, extra,
                       page_token)
        code, resp = http_get(url, timeout=60.0)
        if code != 200:
            raise SystemExit(f"pull failed http={code} {resp} url={url}")
        for sym, bars in (resp.get("bars") or {}).items():
            for b in bars or []:
                if any(b.get(k) is None for k in ("t", "o", "h", "l", "c")):
                    continue
                conn.execute(
                    "INSERT INTO bars(venue,symbol,timeframe,timestamp,open,"
                    "high,low,close,volume,source) "
                    "VALUES(?,?,?,?,?,?,?,?,?,'backfill') "
                    "ON CONFLICT(venue,symbol,timeframe,timestamp) DO UPDATE "
                    "SET open=excluded.open, high=excluded.high, "
                    "low=excluded.low, close=excluded.close, "
                    "volume=excluded.volume, source=excluded.source",
                    ("alpaca", sym, "5min", b["t"], float(b["o"]),
                     float(b["h"]), float(b["l"]), float(b["c"]),
                     float(b.get("v", 0) or 0)))
                written[sym] = written.get(sym, 0) + 1
        conn.commit()
        page_token = resp.get("next_page_token")
        if not page_token:
            break
        if page % 25 == 0:
            print(f"  page {page}: {sum(written.values())} rows", flush=True)
        time.sleep(PAGE_SLEEP_S)
    return written


BIAS_NOTE = ("selection bias: these 8 symbols were chosen in 2026 for being "
             "liquid and prominent, so history before 2026 measures names "
             "that turned out to be winners; expect an optimistic tilt, "
             "especially on NVDA-era equity results")


def load(analysis_db: str, equity_feed: str) -> dict:
    if os.path.abspath(analysis_db) == os.path.abspath(PRODUCTION_DB):
        raise SystemExit("refusing to load into the production database")
    conn = make_analysis_db(analysis_db)
    report: dict = {"db": analysis_db, "written": {}}
    print(f"pull equities from {EQUITY_START} feed={equity_feed} "
          "adjustment=split", flush=True)
    report["written"].update(pull_symbols(
        conn, STOCK_BARS, EQUITIES, EQUITY_START,
        f"&adjustment=split&feed={equity_feed}"))
    print(f"pull crypto from {CRYPTO_START}", flush=True)
    report["written"].update(pull_symbols(
        conn, CRYPTO_BARS, CRYPTO, CRYPTO_START, ""))
    meta = {
        "loaded_at": dt.datetime.now(dt.timezone.utc).isoformat(),
        "loader": "scripts/deep_history_20260724.py",
        "equity_endpoint": STOCK_BARS,
        "crypto_endpoint": CRYPTO_BARS,
        "equity_feed": equity_feed,
        "equity_adjustment": "split",
        "pull_end": PULL_END,
        "bias_note": BIAS_NOTE,
    }
    for k, v in meta.items():
        conn.execute("INSERT OR REPLACE INTO analysis_meta(key,value) "
                     "VALUES(?,?)", (k, v))
    conn.commit()
    report["meta"] = meta
    return report


def split_proofs(conn: sqlite3.Connection) -> list[dict]:
    """Prove each known split leaves no artificial gap in the loaded series."""
    out = []
    for ev in SPLIT_EVENTS:
        sym, day, ratio = ev["symbol"], ev["date"], ev["ratio"]
        before = conn.execute(
            "SELECT timestamp, close FROM bars WHERE symbol=? AND "
            "timeframe='5min' AND timestamp < ? ORDER BY timestamp DESC "
            "LIMIT 1", (sym, f"{day}T00:00:00Z")).fetchone()
        after = conn.execute(
            "SELECT timestamp, open FROM bars WHERE symbol=? AND "
            "timeframe='5min' AND timestamp >= ? ORDER BY timestamp ASC "
            "LIMIT 1", (sym, f"{day}T00:00:00Z")).fetchone()
        row = {"symbol": sym, "event": f"{ratio:g}-for-1 on {day}"}
        if not before or not after:
            row["status"] = "unprovable: series does not span the event"
            out.append(row)
            continue
        gap = after[1] / before[1] - 1.0
        unadjusted_gap = 1.0 / ratio - 1.0
        row.update({
            "last_close_before": {"ts": before[0], "px": before[1]},
            "first_open_after": {"ts": after[0], "px": after[1]},
            "gap_pct": round(gap * 100, 2),
            "unadjusted_would_show_pct": round(unadjusted_gap * 100, 2),
            "status": ("adjusted: no artificial gap" if abs(gap) < 0.15
                       else "FAILED: gap looks unadjusted"),
        })
        out.append(row)
    return out


def per_symbol_year(conn: sqlite3.Connection) -> dict:
    """Bars, sessions, volume presence, and longest no-bar gap per year."""
    out: dict = {}
    rows = conn.execute(
        "SELECT symbol, substr(timestamp,1,4) yr, COUNT(*), "
        "COUNT(DISTINCT substr(timestamp,1,10)), "
        "SUM(CASE WHEN volume > 0 THEN 1 ELSE 0 END) "
        "FROM bars WHERE timeframe='5min' GROUP BY symbol, yr").fetchall()
    for sym, yr, n, sessions, vol_n in rows:
        out.setdefault(sym, {})[yr] = {
            "bars": n, "sessions": sessions,
            "volume_presence": round(vol_n / n, 4) if n else 0.0}
    for sym in out:
        dates = [r[0] for r in conn.execute(
            "SELECT DISTINCT substr(timestamp,1,10) FROM bars WHERE symbol=? "
            "AND timeframe='5min' ORDER BY 1", (sym,))]
        worst, worst_at = 0, ""
        for a, b in zip(dates, dates[1:]):
            d = (dt.date.fromisoformat(b) - dt.date.fromisoformat(a)).days
            if d > worst:
                worst, worst_at = d, f"{a} to {b}"
        limit = 4 if "/" not in sym else 2
        out[sym]["longest_gap"] = {
            "days": worst, "span": worst_at,
            "flag": worst > limit}
    return out


def validate(analysis_db: str, expect_hash: str | None) -> dict:
    conn = sqlite3.connect(analysis_db)
    rep: dict = {"db": analysis_db}
    rep["meta"] = dict(conn.execute(
        "SELECT key, value FROM analysis_meta").fetchall())
    rep["split_proofs"] = split_proofs(conn)
    rep["per_symbol_year"] = per_symbol_year(conn)
    rep["usable"] = dict(conn.execute(
        "SELECT symbol, COUNT(*) FROM bars WHERE timeframe='5min' AND "
        "source IN ('real_feed','backfill') AND "
        "COALESCE(volume_source,'') != 'fabricated_zeroed' "
        "GROUP BY symbol").fetchall())

    # Production freeze check.
    h = hashlib.sha256()
    with open(PRODUCTION_DB, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    prod = sqlite3.connect(f"file:{PRODUCTION_DB}?mode=ro", uri=True)
    rep["production"] = {
        "sha256": h.hexdigest(),
        "expected_sha256": expect_hash,
        "frozen": (h.hexdigest() == expect_hash) if expect_hash else None,
        "rows": {t: prod.execute(
            f"SELECT COUNT(*) FROM {t}").fetchone()[0]
            for t in ("bars", "events", "trades", "positions")},
    }
    return rep


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("cmd", choices=["probe", "load", "validate"])
    ap.add_argument("--analysis-db", default=ANALYSIS_DB_DEFAULT)
    ap.add_argument("--equity-feed", default="sip",
                    help="historical equity feed, set from the probe result")
    ap.add_argument("--expect-hash", default=None,
                    help="production db sha256 captured before the load")
    args = ap.parse_args()
    if args.cmd == "probe":
        print(json.dumps(probe(), indent=2))
    elif args.cmd == "load":
        print(json.dumps(load(args.analysis_db, args.equity_feed), indent=2))
    else:
        print(json.dumps(validate(args.analysis_db, args.expect_hash),
                         indent=2))


if __name__ == "__main__":
    main()
