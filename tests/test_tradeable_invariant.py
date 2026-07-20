"""THE tradeable invariant: one predicate, every consumer, both directions.

The 2026-07-20 incident is the spec. Six symbols received real bars on time.
Two watchlist symbols Alpaca has never served (MANA/USD, RUNE/USD) received
fabricated synthetic walk bars at the same timestamps, the stack-level
feed_substitution condition read them as a live substitution after the grace,
and the watchdog stopped the whole stack.

These tests pin the invariant end to end:
  * the predicate itself (real history in, tradeable out, every degradation),
  * the single-source-of-truth guards (Python consumers call the predicate,
    the C++ source set cannot drift from the Python one, no runtime file
    re-derives the check, the fabrication site stays removed),
  * symbol_unavailable vs feed_substitution never sharing an alarm,
  * the scoped stop authority (any_tradeable_serving) in both directions,
  * the kill switch never auto-resumed.

No network, nothing binds: tmp SQLite DBs, monkeypatches, and source scrapes.
"""
from __future__ import annotations

import os
import re
import sqlite3
from datetime import datetime, timedelta, timezone

import pytest

from market_data import alpaca_source, tradeable
from ops import watchdog

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


@pytest.fixture(autouse=True)
def _isolated_state(tmp_path, monkeypatch):
    monkeypatch.setenv("MAL_RUN_DIR", str(tmp_path / "run"))


def _ago(seconds: int) -> str:
    dt = datetime.now(timezone.utc) - timedelta(seconds=seconds)
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def _mk_db(tmp_path, bars, name="feed.db"):
    db = tmp_path / name
    conn = sqlite3.connect(db)
    alpaca_source.ensure_bars_schema(conn)
    for symbol, ts, source in bars:
        conn.execute(
            "INSERT INTO bars(venue,symbol,timeframe,timestamp,open,high,low,"
            "close,volume,source) VALUES('alpaca',?,?,?,1,2,0.5,1.5,10,?)",
            (symbol, "5min", ts, source))
    conn.commit()
    conn.close()
    return str(db)


def _pin(monkeypatch, symbols, *, real=True, discovery=False, rth=True):
    monkeypatch.setattr(watchdog.stack, "whitelist", lambda: list(symbols))
    monkeypatch.setattr(watchdog, "_real_feed_mode", lambda: real)
    monkeypatch.setattr(watchdog, "_discovery_enabled", lambda: discovery)
    monkeypatch.setattr(watchdog, "_equity_market_open", lambda: rth)


def _read(path: str) -> str:
    with open(os.path.join(REPO, path)) as fh:
        return fh.read()


# --- The predicate itself -----------------------------------------------------

def test_real_feed_history_is_tradeable(tmp_path):
    db = _mk_db(tmp_path, [("BTC/USD", _ago(60), "real_feed")])
    conn = sqlite3.connect(db)
    assert tradeable.symbol_is_tradeable(conn, "BTC/USD") is True
    conn.close()


def test_backfill_history_is_tradeable(tmp_path):
    # A freshly backfilled symbol has not ticked live yet but the venue
    # provably serves it: real history.
    db = _mk_db(tmp_path, [("AAVE/USD", _ago(86400), "backfill")])
    conn = sqlite3.connect(db)
    assert tradeable.symbol_is_tradeable(conn, "AAVE/USD") is True
    conn.close()


def test_synthetic_only_history_is_not_tradeable(tmp_path):
    # THE MANA/USD shape: bars exist, every one fabricated. Not tradeable.
    db = _mk_db(tmp_path, [("MANA/USD", _ago(60), "synthetic"),
                           ("MANA/USD", _ago(360), "synthetic")])
    conn = sqlite3.connect(db)
    assert tradeable.symbol_is_tradeable(conn, "MANA/USD") is False
    conn.close()


def test_zero_bars_is_not_tradeable(tmp_path):
    db = _mk_db(tmp_path, [])
    conn = sqlite3.connect(db)
    assert tradeable.symbol_is_tradeable(conn, "RUNE/USD") is False
    conn.close()


def test_unknown_only_history_is_not_tradeable(tmp_path):
    # unknown is NEVER real (core/provenance.hpp rule).
    db = _mk_db(tmp_path, [("SOL/USD", _ago(60), "unknown")])
    conn = sqlite3.connect(db)
    assert tradeable.symbol_is_tradeable(conn, "SOL/USD") is False
    conn.close()


def test_pre_migration_db_reads_any_bar_as_history(tmp_path):
    # No source column: provenance is unprovable, keep the old semantics.
    db = tmp_path / "old.db"
    conn = sqlite3.connect(db)
    conn.execute(
        "CREATE TABLE bars (venue TEXT, symbol TEXT, timeframe TEXT,"
        " timestamp TEXT, open REAL, high REAL, low REAL, close REAL,"
        " volume REAL)")
    conn.execute(
        "INSERT INTO bars VALUES('alpaca','BTC/USD','5min',?,1,2,0.5,1.5,10)",
        (_ago(60),))
    conn.commit()
    assert tradeable.symbol_is_tradeable(conn, "BTC/USD") is True
    assert tradeable.symbol_is_tradeable(conn, "MANA/USD") is False
    conn.close()


def test_missing_bars_table_is_no_history(tmp_path):
    conn = sqlite3.connect(tmp_path / "empty.db")
    assert tradeable.symbol_is_tradeable(conn, "BTC/USD") is False
    conn.close()


def test_untradeable_helper_preserves_order(tmp_path):
    db = _mk_db(tmp_path, [("BTC/USD", _ago(60), "real_feed")])
    conn = sqlite3.connect(db)
    assert tradeable.untradeable_symbols(
        conn, ["MANA/USD", "BTC/USD", "RUNE/USD"]) == ["MANA/USD", "RUNE/USD"]
    conn.close()


# --- Single source of truth: consumers call THE predicate ---------------------

def test_watchdog_imports_the_predicate_not_a_copy():
    src = _read("ops/watchdog.py")
    assert "from market_data.tradeable import" in src
    assert "symbol_is_tradeable" in src
    # The old private copy of the source set stays dead.
    assert "_REAL_SOURCES" not in src


def test_discovery_onboarding_calls_the_predicate():
    src = _read("discovery/run.py")
    assert "symbol_is_tradeable" in src


def test_no_runtime_file_rederives_the_history_check():
    # A new bar-consuming path must call the predicate, not write a new
    # provenance query. The `source IN` probe may exist in exactly one
    # runtime module: the predicate itself.
    offenders = []
    for pkg in ("account_manager", "adaptive", "api_server", "discovery",
                "llm_consensus", "market_data", "ml_factor", "ops",
                "python_bridge", "research_satellite", "rl_advisory", "ui",
                "whale_signal"):
        root = os.path.join(REPO, pkg)
        for dirpath, _dirs, files in os.walk(root):
            if "__pycache__" in dirpath:
                continue
            for f in files:
                if not f.endswith(".py"):
                    continue
                path = os.path.join(dirpath, f)
                with open(path) as fh:
                    body = fh.read()
                if re.search(r"source\s+IN\s*\(", body):
                    rel = os.path.relpath(path, REPO)
                    if rel != os.path.join("market_data", "tradeable.py"):
                        offenders.append(rel)
    assert offenders == [], (
        "these files re-derive the real-history check instead of calling "
        f"market_data.tradeable.symbol_is_tradeable: {offenders}")


def test_cpp_source_set_cannot_drift_from_python():
    # Storage::has_real_bars is the C++ read of the same invariant. Its SQL
    # must name exactly the Python REAL_SOURCES.
    cpp = _read("storage/storage.cpp")
    m = re.search(r"has_real_bars[\s\S]{0,400}?source IN \(([^)]*)\)", cpp)
    assert m, "Storage::has_real_bars lost its source IN (...) clause"
    cpp_sources = sorted(re.findall(r"'([a-z_]+)'", m.group(1)))
    assert cpp_sources == sorted(tradeable.REAL_SOURCES)


def test_cpp_consumers_call_the_predicate():
    engine = _read("core/engine.cpp")
    # The substitution alarm consults the predicate.
    sub = re.search(r"void Engine::check_feed_substitution[\s\S]*?\n\}",
                    engine)
    assert sub and "symbol_is_tradeable(" in sub.group(0), (
        "check_feed_substitution no longer consults symbol_is_tradeable: an "
        "unavailable symbol could raise a stack-level substitution again")
    # The entry path consults the predicate.
    entry = re.search(r"ENTRY path[\s\S]{0,1200}?allows_entry", engine)
    assert entry and "symbol_is_tradeable(" in entry.group(0), (
        "the entry path no longer consults symbol_is_tradeable before "
        "evaluating")


def test_alpaca_feed_fabrication_stays_removed():
    # The mutation guard's lexical half (the behavioral half is the C++ test
    # feed_no_fabrication): AlpacaFeed::poll must never tag a tick synthetic,
    # because it must never emit a tick that is not a real venue quote.
    md = _read("market_data/market_data.cpp")
    poll = re.search(r"AlpacaFeed::poll[\s\S]*?\n\}\n", md)
    assert poll, "AlpacaFeed::poll not found"
    body = poll.group(0)
    assert 'data_source = "synthetic"' not in body, (
        "AlpacaFeed::poll tags ticks synthetic again: the walk fallback is "
        "back")
    assert "next_uniform() - 0.5) * 0.04" not in body, (
        "the deterministic walk shock is back in AlpacaFeed::poll")


# --- The two conditions never share an alarm ----------------------------------

def test_unavailable_symbol_with_in_window_synthetic_is_never_substitution(
        tmp_path, monkeypatch):
    # The sharpest incident shape: fabricated bars INSIDE the recency window
    # for a symbol with no real history. symbol_unavailable, never
    # feed_substitution.
    _pin(monkeypatch, ["BTC/USD", "MANA/USD"])
    db = _mk_db(tmp_path, [("BTC/USD", _ago(60), "real_feed"),
                           ("MANA/USD", _ago(60), "synthetic")])
    out = watchdog.feed_ok(900, db, recency_window_seconds=900)
    assert out["unavailable_symbols"] == ["MANA/USD"]
    assert out["non_real_symbols"] == []
    assert out["stale_symbols"] == []
    assert out["symbols"]["MANA/USD"]["reason"] == "symbol_unavailable"
    assert out["ok"] is True


def test_served_symbol_going_non_real_is_substitution_not_unavailable(
        tmp_path, monkeypatch):
    _pin(monkeypatch, ["LDO/USD"])
    db = _mk_db(tmp_path, [("LDO/USD", _ago(86400), "backfill"),
                           ("LDO/USD", _ago(60), "synthetic")])
    out = watchdog.feed_ok(900, db, recency_window_seconds=900)
    assert out["unavailable_symbols"] == []
    assert out["non_real_symbols"] == ["LDO/USD"]
    assert out["ok"] is False


def test_check_health_reports_the_two_conditions_distinctly(
        tmp_path, monkeypatch):
    _pin(monkeypatch, ["BTC/USD", "MANA/USD"])
    db = _mk_db(tmp_path, [("BTC/USD", _ago(60), "real_feed"),
                           ("MANA/USD", _ago(60), "synthetic")])
    monkeypatch.setattr(watchdog, "_db_path", lambda: db)
    monkeypatch.setattr(watchdog, "bridge_state",
                        lambda: {"reachable": True, "status": "ok",
                                 "degraded": [], "fd_count": 40})
    monkeypatch.setattr(watchdog.stack, "http_ok", lambda *a, **k: True)
    monkeypatch.setattr(watchdog.stack, "stack_running",
                        lambda: {"running": True})
    monkeypatch.setattr(watchdog, "kill_tripped", lambda: False)
    h = watchdog.check_health({"bar_staleness_seconds": 900,
                               "substitution_recency_window_seconds": 900})
    assert h["feed_symbol_unavailable"] == ["MANA/USD"]
    assert h["feed_substitution"] is False
    assert h["feed_serving"] is True
    assert h["healthy"] is True


# --- The scoped stop authority ------------------------------------------------

def test_any_tradeable_serving_predicate():
    assert watchdog.any_tradeable_serving({"serving_symbols": ["BTC/USD"]})
    assert not watchdog.any_tradeable_serving({"serving_symbols": []})
    assert not watchdog.any_tradeable_serving({})


def test_serving_holds_the_feed_not_broken_despite_unavailable_and_stale(
        tmp_path, monkeypatch):
    # One serving symbol, one stale, two unavailable: named, contained, NOT
    # broken, regardless of how many unserviceable symbols exist.
    _pin(monkeypatch, ["BTC/USD", "SOL/USD", "MANA/USD", "RUNE/USD"])
    db = _mk_db(tmp_path, [("BTC/USD", _ago(60), "real_feed"),
                           ("SOL/USD", _ago(86400), "backfill"),
                           ("MANA/USD", _ago(60), "synthetic")])
    out = watchdog.feed_ok(900, db)
    assert out["serving_symbols"] == ["BTC/USD"]
    assert out["stale_symbols"] == ["SOL/USD"]
    assert sorted(out["unavailable_symbols"]) == ["MANA/USD", "RUNE/USD"]
    assert out["ok"] is True


def test_nothing_serving_is_broken_and_substitution_always_is(
        tmp_path, monkeypatch):
    # Direction two, twice: a dead feed (all tradeable stale, nothing served)
    # is broken, and a live substitution is broken EVEN WHILE another symbol
    # is served.
    _pin(monkeypatch, ["BTC/USD", "ETH/USD"])
    dead = _mk_db(tmp_path, [("BTC/USD", _ago(86400), "real_feed"),
                             ("ETH/USD", _ago(86400), "backfill")],
                  name="dead.db")
    assert watchdog.feed_ok(900, dead)["ok"] is False

    sub = _mk_db(tmp_path, [("BTC/USD", _ago(60), "real_feed"),
                            ("ETH/USD", _ago(86400), "backfill"),
                            ("ETH/USD", _ago(60), "synthetic")],
                 name="sub.db")
    out = watchdog.feed_ok(900, sub)
    assert out["serving_symbols"] == ["BTC/USD"]
    assert out["non_real_symbols"] == ["ETH/USD"]
    assert out["ok"] is False, (
        "substitution must outrank the serving predicate: direction two is "
        "not weakened by direction one")


# --- The kill switch stays manual ---------------------------------------------

def test_kill_trip_with_unavailable_symbols_is_never_auto_resumed(
        monkeypatch):
    notes = []
    health = {"engine": True, "bridge": True, "bridge_status": "ok",
              "bridge_degraded": [], "backend": True, "feed_fresh": True,
              "feed_source": "real_feed", "feed_ok": True,
              "feed_stale_symbols": [], "feed_non_real_symbols": [],
              "feed_symbol_unavailable": ["MANA/USD"],
              "feed_out_of_window_non_real": [], "feed_substitution": False,
              "kill_tripped": True, "healthy": False}
    posts = []
    monkeypatch.setattr(watchdog, "check_health", lambda cfg=None: health)
    monkeypatch.setattr(watchdog, "_supervisor_post",
                        lambda p, timeout=30: posts.append(p) or {"ok": True})
    monkeypatch.setattr(watchdog, "notify",
                        lambda msg, cfg=None, title="": notes.append(msg)
                        or True)
    res = watchdog.run_once({})
    assert res["action"] == "kill_notified"
    assert posts == []
    assert any("Manual resume required" in n for n in notes)
