"""The backtest harness: no lookahead, provenance-clean feed, honest stats.

LOOKAHEAD PROOF (Task 2): run the harness on a DB, then corrupt every bar
after a cutoff to absurd prices and run again. Every decision at or before
the cutoff must be byte-identical, or some computation read the future.

Provenance: synthetic/unknown/quarantined rows never reach the tape.
Statistics: below MIN_SAMPLE the report refuses (insufficient_sample), every
ok group carries intervals, folds are chronological.
"""
from __future__ import annotations

import datetime
import json
import math
import os
import shutil
import sqlite3
import subprocess

import pytest

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BIN = os.path.join(REPO, "build", "mal_backtest")
SCHEMA = os.path.join(REPO, "storage", "schema.sql")


def _mk_db(path: str) -> sqlite3.Connection:
    conn = sqlite3.connect(path)
    with open(SCHEMA) as fh:
        conn.executescript(fh.read())
    # The provenance columns land via runtime ALTER migration in production
    # (storage.cpp init_schema); mirror them here.
    for ddl in ("ALTER TABLE bars ADD COLUMN source TEXT DEFAULT 'unknown'",
                "ALTER TABLE bars ADD COLUMN volume_source TEXT"):
        try:
            conn.execute(ddl)
        except sqlite3.OperationalError:
            pass
    return conn


def _seed_bars(conn, symbol: str, n: int, base_epoch: int = 1767571200,
               source: str = "backfill") -> None:
    for i in range(n):
        ts = datetime.datetime.fromtimestamp(
            base_epoch + i * 300,
            datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        px = 100.0 + 5.0 * math.sin(i / 12.0) + (i % 7) * 0.2
        conn.execute(
            "INSERT OR REPLACE INTO bars(venue,symbol,timeframe,timestamp,"
            "open,high,low,close,volume,source) VALUES(?,?,?,?,?,?,?,?,?,?)",
            ("alpaca", symbol, "5min", ts, px, px + 0.8, px - 0.8,
             px + 0.3, 1000.0 + i, source))


def _run(db: str, *extra: str) -> list[dict]:
    out = subprocess.run(
        [BIN, "--db", db, "--profile", "swing", "--symbols", "BTC/USD",
         "--emit-rejections", *extra],
        capture_output=True, text=True, check=True)
    return [json.loads(x) for x in out.stdout.splitlines() if x.strip()]


@pytest.mark.skipif(not os.path.exists(BIN), reason="mal_backtest not built")
def test_no_lookahead_corrupting_future_bars_changes_nothing(tmp_path):
    db = str(tmp_path / "bt.db")
    conn = _mk_db(db)
    _seed_bars(conn, "BTC/USD", 500)
    conn.commit()
    conn.close()
    cutoff_epoch = 1767571200 + 400 * 300
    cutoff = datetime.datetime.fromtimestamp(
        cutoff_epoch, datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    before = [d for d in _run(db)
              if d.get("ts") and d["ts"] <= cutoff and d["t"] != "summary"]

    db2 = str(tmp_path / "bt2.db")
    shutil.copy(db, db2)
    conn = sqlite3.connect(db2)
    conn.execute(
        "UPDATE bars SET open=999999, high=999999, low=999999, close=999999 "
        "WHERE timestamp > ?", (cutoff,))
    conn.commit()
    conn.close()
    after = [d for d in _run(db2)
             if d.get("ts") and d["ts"] <= cutoff and d["t"] != "summary"]
    assert before == after, (
        "a decision at or before the cutoff changed when only FUTURE bars "
        "were corrupted: some computation reads ahead")
    assert len(before) > 50, "the proof must cover a real number of decisions"


@pytest.mark.skipif(not os.path.exists(BIN), reason="mal_backtest not built")
def test_provenance_excluded_rows_never_reach_the_tape(tmp_path):
    db = str(tmp_path / "bt.db")
    conn = _mk_db(db)
    _seed_bars(conn, "BTC/USD", 120, source="backfill")
    _seed_bars(conn, "BTC/USD", 120, base_epoch=1767571200 + 200 * 300,
               source="synthetic")
    # Quarantined-volume rows: real provenance, but marked by the quarantine.
    conn.execute(
        "UPDATE bars SET volume_source='fabricated_zeroed' "
        "WHERE source='backfill' AND rowid % 10 = 0")
    conn.commit()
    conn.close()
    recs = _run(db)
    bars = next(d for d in recs if d["t"] == "bars")
    # Synthetic block invisible, quarantined rows excluded.
    assert bars["usable"] < 120, "quarantined rows must be excluded"
    assert 100 <= bars["usable"] <= 120


def test_report_refuses_below_min_sample_and_carries_intervals(tmp_path):
    from backtest import report as rp
    p = tmp_path / "run.jsonl"
    rows = [{"t": "trade", "symbol": "X", "factor": "reversion",
             "category": "crypto",
             "entry_ts": f"2026-07-{10 + i // 10:02d}T00:0{i % 10}:00Z",
             "exit_ts": "x", "entry_px": 100, "exit_px": 101,
             "reason": "target", "ret": 0.01 if i % 3 else -0.005,
             "pnl": 1.0 if i % 3 else -0.5, "bars_held": 3,
             "ambiguous": 0, "atr_z_at_entry": 0.0, "fill_gap": 0.0,
             "equity": 100000} for i in range(40)]
    with open(p, "w") as fh:
        for r in rows:
            fh.write(json.dumps(r) + "\n")
        fh.write(json.dumps({"t": "summary", "mode": "backtest"}) + "\n")
    rep = rp.report(str(p))
    assert rep["pooled"]["status"] == "ok"
    assert "win_rate_ci" in rep["pooled"] and "mean_ret_ci" in rep["pooled"]
    # Folds are chronological and each small fold REFUSES.
    assert all(f["status"] == "insufficient_sample" for f in rep["folds"])
    # A thin group refuses rather than concluding.
    thin = rp.stats_for(rows[:5])
    assert thin["status"] == "insufficient_sample"
    assert "no conclusion" in thin["note"]
