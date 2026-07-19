"""Feed integrity: provenance writes, capability health, watchdog, quarantine.

Everything here runs against temp DBs and monkeypatched probes. No real
network call, no real socket beyond what a monkeypatch stubs, and the bind
never leaves loopback because nothing here serves at all.

The 2026-07-17 outage is the spec: synthetic bars advanced for 19 hours, the
bridge answered liveness probes while sick, and the watchdog read the feed as
fresh. Each test pins one of the ways that must now be impossible.
"""
from __future__ import annotations

import sqlite3

import pytest

from market_data import alpaca_source
from ml_factor.real_dataset import count_closed_trades
from ops import watchdog
from scripts.quarantine_synthetic_bars_20260717 import quarantine

_TRADES_DDL = (
    "CREATE TABLE trades (id INTEGER PRIMARY KEY AUTOINCREMENT, ts TEXT,"
    " venue TEXT, symbol TEXT, market TEXT, category TEXT, side TEXT,"
    " qty REAL, price REAL, notional REAL, fee REAL, mode TEXT, pnl REAL,"
    " outcome TEXT, combined_conf REAL, combined_edge REAL,"
    " sleeve TEXT DEFAULT 'quant_core', origin TEXT DEFAULT 'strategy',"
    " bar_source TEXT DEFAULT 'unknown')"
)


def _bar(conn, ts, source, symbol="BTC/USD", timeframe="5min"):
    conn.execute(
        "INSERT INTO bars(venue,symbol,timeframe,timestamp,open,high,low,"
        "close,volume,source) VALUES('alpaca',?,?,?,1,2,0.5,1.5,10,?)",
        (symbol, timeframe, ts, source))


def _trade(conn, ts, outcome, origin="strategy", bar_source="unknown",
           pnl=1.0, symbol="BTC/USD"):
    conn.execute(
        "INSERT INTO trades(ts,venue,symbol,side,mode,pnl,outcome,origin,"
        "bar_source) VALUES(?,?,?,?,?,?,?,?,?)",
        (ts, "alpaca", symbol, "buy", "paper", pnl, outcome, origin,
         bar_source))


# --- Task 1: provenance on every Python write path, no default to real ------

def test_backfill_upsert_writes_backfill_source(tmp_path):
    db = tmp_path / "bars.db"
    conn = sqlite3.connect(db)
    alpaca_source.ensure_bars_schema(conn)
    n = alpaca_source._upsert_bars(
        conn, "alpaca", "BTC/USD", "5min",
        [{"t": "2026-07-18T10:00:00Z", "o": 1, "h": 2, "l": 0.5, "c": 1.5,
          "v": 3}])
    conn.commit()
    assert n == 1
    row = conn.execute("SELECT source FROM bars").fetchone()
    assert row[0] == "backfill"
    conn.close()


def test_migration_marks_existing_rows_unknown_not_real(tmp_path):
    db = tmp_path / "old.db"
    conn = sqlite3.connect(db)
    # A pre-provenance DB: bars table without the source column.
    conn.execute(
        "CREATE TABLE bars (id INTEGER PRIMARY KEY AUTOINCREMENT,"
        " venue TEXT NOT NULL, symbol TEXT NOT NULL, timeframe TEXT NOT NULL,"
        " timestamp TEXT NOT NULL, open REAL NOT NULL, high REAL NOT NULL,"
        " low REAL NOT NULL, close REAL NOT NULL, volume REAL NOT NULL,"
        " UNIQUE(venue, symbol, timeframe, timestamp))")
    conn.execute(
        "INSERT INTO bars(venue,symbol,timeframe,timestamp,open,high,low,"
        "close,volume) VALUES('alpaca','BTC/USD','5min',"
        "'2026-07-01T00:00:00Z',1,2,0.5,1.5,10)")
    alpaca_source.ensure_bars_schema(conn)
    alpaca_source.ensure_bars_schema(conn)  # idempotent
    row = conn.execute(
        "SELECT COALESCE(source,'unknown') FROM bars").fetchone()
    assert row[0] == "unknown"
    conn.close()


# --- Task 4: bridge health verifies capability, not liveness -----------------

def test_health_degraded_when_fresh_file_read_fails(monkeypatch):
    from python_bridge import server
    monkeypatch.setattr(server, "_fresh_file_check",
                        lambda: "fail (OSError)")
    monkeypatch.setattr(server, "_fresh_socket_check", lambda: "ok")
    monkeypatch.setattr(server, "_quote_capability", lambda: "ok")
    payload = server.health_payload()
    assert payload["status"] == "degraded"
    assert payload["degraded"] == ["fresh_file"]


def test_health_degraded_when_fresh_socket_fails_though_process_alive(
        monkeypatch):
    # The outage shape: the process answers (this function runs) and pooled
    # paths work, but a brand-new socket cannot be opened.
    from python_bridge import server
    monkeypatch.setattr(server, "_fresh_file_check", lambda: "ok")
    monkeypatch.setattr(server, "_fresh_socket_check",
                        lambda: "fail (OSError)")
    monkeypatch.setattr(server, "_quote_capability", lambda: "ok")
    payload = server.health_payload()
    assert payload["status"] == "degraded"
    assert payload["degraded"] == ["fresh_socket"]


def test_health_up_when_capabilities_ok_and_quote_skipped_keyless(monkeypatch):
    # Keyless (offline paper loop) is skipped, not degraded.
    from python_bridge import server
    monkeypatch.setattr(server, "_fresh_file_check", lambda: "ok")
    monkeypatch.setattr(server, "_fresh_socket_check", lambda: "ok")
    monkeypatch.setattr(server, "_quote_capability",
                        lambda: "skipped (no data key)")
    payload = server.health_payload()
    assert payload["status"] == "ok"
    assert payload["degraded"] == []


def test_fresh_file_check_reports_real_failure(monkeypatch, tmp_path):
    # Point the control path at a directory: open() raises, the check fails,
    # and the failure names the exception class, never a path or a key.
    from llm_consensus import control_file
    from python_bridge import server
    monkeypatch.setattr(control_file, "control_path",
                        lambda: str(tmp_path))
    assert server._fresh_file_check().startswith("fail (")


# --- Task 5: the watchdog acts on degraded and synthetic ---------------------

def _feed_db(tmp_path, ts, source):
    db = tmp_path / "feed.db"
    conn = sqlite3.connect(db)
    alpaca_source.ensure_bars_schema(conn)
    _bar(conn, ts, source)
    conn.commit()
    conn.close()
    return str(db)


def _fresh_ts():
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def test_advancing_synthetic_bars_do_not_read_healthy(tmp_path, monkeypatch):
    # THE outage check: fresh timestamp, synthetic source, real feed mode.
    monkeypatch.setattr(watchdog, "tradeable_symbols",
                        lambda db=None: ["BTC/USD"])
    monkeypatch.setattr(watchdog, "_real_feed_mode", lambda: True)
    db = _feed_db(tmp_path, _fresh_ts(), "synthetic")
    out = watchdog.feed_ok(900, db)
    assert out["fresh"] is True
    assert out["ok"] is False
    assert out["source"] == "synthetic"


def test_fresh_real_bars_read_healthy(tmp_path, monkeypatch):
    monkeypatch.setattr(watchdog, "tradeable_symbols",
                        lambda db=None: ["BTC/USD"])
    monkeypatch.setattr(watchdog, "_real_feed_mode", lambda: True)
    db = _feed_db(tmp_path, _fresh_ts(), "real_feed")
    assert watchdog.feed_ok(900, db)["ok"] is True


def test_stale_real_bars_read_unhealthy(tmp_path, monkeypatch):
    monkeypatch.setattr(watchdog, "tradeable_symbols",
                        lambda db=None: ["BTC/USD"])
    monkeypatch.setattr(watchdog, "_real_feed_mode", lambda: True)
    db = _feed_db(tmp_path, "2026-07-01T00:00:00Z", "real_feed")
    out = watchdog.feed_ok(900, db)
    assert out["fresh"] is False and out["ok"] is False


def test_offline_mode_not_held_to_real_bar(tmp_path, monkeypatch):
    # synthetic_regimes runs on synthetic bars by design.
    monkeypatch.setattr(watchdog, "tradeable_symbols",
                        lambda db=None: ["BTC/USD"])
    monkeypatch.setattr(watchdog, "_real_feed_mode", lambda: False)
    db = _feed_db(tmp_path, _fresh_ts(), "synthetic")
    assert watchdog.feed_ok(900, db)["ok"] is True


def test_pre_migration_db_falls_back_to_freshness(tmp_path, monkeypatch):
    monkeypatch.setattr(watchdog, "tradeable_symbols",
                        lambda db=None: ["BTC/USD"])
    monkeypatch.setattr(watchdog, "_real_feed_mode", lambda: True)
    db = tmp_path / "old.db"
    conn = sqlite3.connect(db)
    conn.execute(
        "CREATE TABLE bars (venue TEXT, symbol TEXT, timeframe TEXT,"
        " timestamp TEXT, open REAL, high REAL, low REAL, close REAL,"
        " volume REAL)")
    conn.execute(
        "INSERT INTO bars VALUES('alpaca','BTC/USD','5min',?,1,2,0.5,1.5,10)",
        (_fresh_ts(),))
    conn.commit()
    conn.close()
    out = watchdog.feed_ok(900, str(db))
    assert out["provenance_checked"] is False
    assert out["ok"] is True  # freshness only: the column does not exist


def test_watchdog_treats_degraded_bridge_as_failure(monkeypatch):
    monkeypatch.setattr(watchdog.stack, "stack_running",
                        lambda: {"running": True})
    monkeypatch.setattr(watchdog.stack, "http_ok",
                        lambda *a, **k: True)
    monkeypatch.setattr(
        watchdog, "bridge_state",
        lambda: {"reachable": True, "status": "degraded",
                 "degraded": ["fresh_socket"]})
    monkeypatch.setattr(watchdog, "feed_ok",
                        lambda *a, **k: {"fresh": True, "source": "real_feed",
                                         "real": True, "ok": True,
                                         "provenance_checked": True})
    monkeypatch.setattr(watchdog, "kill_tripped", lambda: False)
    h = watchdog.check_health({})
    assert h["bridge"] is False
    assert h["bridge_status"] == "degraded"
    assert h["healthy"] is False
    assert "DEGRADED" in watchdog._status_line(h)


def test_watchdog_flags_non_real_feed_in_status_line(monkeypatch):
    monkeypatch.setattr(watchdog.stack, "stack_running",
                        lambda: {"running": True})
    monkeypatch.setattr(watchdog.stack, "http_ok", lambda *a, **k: True)
    monkeypatch.setattr(
        watchdog, "bridge_state",
        lambda: {"reachable": True, "status": "ok", "degraded": []})
    monkeypatch.setattr(watchdog, "feed_ok",
                        lambda *a, **k: {"fresh": True, "source": "synthetic",
                                         "real": False, "ok": False,
                                         "provenance_checked": True})
    monkeypatch.setattr(watchdog, "kill_tripped", lambda: False)
    h = watchdog.check_health({})
    assert h["healthy"] is False
    assert "NON-REAL (synthetic)" in watchdog._status_line(h)


# --- Task 6: quarantine and the real-fill gates ------------------------------

def test_count_closed_trades_excludes_synthetic_bar_fills(tmp_path):
    conn = sqlite3.connect(tmp_path / "t.db")
    conn.execute(_TRADES_DDL)
    _trade(conn, "2026-07-17T10:00:00Z", "win", bar_source="real_feed")
    _trade(conn, "2026-07-17T13:35:10Z", "win", bar_source="synthetic")
    _trade(conn, "2026-07-01T00:00:00Z", "win", bar_source="unknown")
    _trade(conn, "2026-07-17T11:00:00Z", "win", origin="rebalance",
           bar_source="real_feed")
    conn.commit()
    # real + unknown count (historical fills predate the column and were
    # real). synthetic excluded. rebalance excluded by the origin rule.
    assert count_closed_trades(conn) == 2
    conn.close()


def test_quarantine_marks_window_bars_and_trades_idempotently(tmp_path):
    db = tmp_path / "q.db"
    conn = sqlite3.connect(db)
    alpaca_source.ensure_bars_schema(conn)
    conn.execute(_TRADES_DDL)
    # Engine-written walk bars inside the window (odd seconds): must mark.
    _bar(conn, "2026-07-17T12:00:06Z", "unknown")
    _bar(conn, "2026-07-17T13:35:07Z", "unknown", symbol="SPY")
    _bar(conn, "2026-07-18T04:00:12Z", "unknown", symbol="QQQ")
    # Backfill-shaped row inside the window (aligned :00): must NOT mark.
    _bar(conn, "2026-07-17T12:05:00Z", "backfill")
    # Real bar outside the window: must NOT mark.
    _bar(conn, "2026-07-17T11:45:28Z", "unknown")
    # The two contaminated fills plus one outside the window.
    _trade(conn, "2026-07-17T13:35:10Z", "open")
    _trade(conn, "2026-07-17T13:50:10Z", "win")
    _trade(conn, "2026-07-17T10:00:00Z", "win")
    conn.commit()
    conn.close()

    first = quarantine(str(db))
    assert first["bars_marked_this_run"] == 3
    assert first["trades_marked_this_run"] == 2
    second = quarantine(str(db))
    assert second["bars_marked_this_run"] == 0
    assert second["trades_marked_this_run"] == 0

    conn = sqlite3.connect(db)
    assert conn.execute(
        "SELECT source FROM bars WHERE timestamp='2026-07-17T12:05:00Z'"
    ).fetchone()[0] == "backfill"
    assert conn.execute(
        "SELECT source FROM bars WHERE timestamp='2026-07-17T11:45:28Z'"
    ).fetchone()[0] == "unknown"
    assert conn.execute(
        "SELECT bar_source FROM trades WHERE ts='2026-07-17T10:00:00Z'"
    ).fetchone()[0] == "unknown"
    conn.close()


def test_weeklog_flags_synthetic_feed_fills(tmp_path):
    from ops import weeklog
    db = tmp_path / "w.db"
    conn = sqlite3.connect(db)
    conn.execute(_TRADES_DDL)
    _trade(conn, "2026-07-17T13:35:10Z", "win", bar_source="synthetic")
    _trade(conn, "2026-07-17T14:00:00Z", "win", bar_source="real_feed")
    conn.commit()
    conn.row_factory = sqlite3.Row
    rows = weeklog._trades_in_window(conn, "2026-07-17T00:00:00Z",
                                     "2026-07-18T00:00:00Z")
    out = weeklog.collect_trades(rows)
    assert out["n_synthetic_feed"] == 1
    conn.close()
