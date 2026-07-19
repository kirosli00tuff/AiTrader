"""Per-symbol watchdog freshness: one stale tradeable symbol is detected BY NAME.

The SOL/USD incident is the spec: it sat 24 hours stale while BTC/USD stayed
current, and the old MAX(timestamp)-over-all-crypto probe reported the feed
fresh throughout. These tests pin that the probe now checks every tradeable
symbol (profile-resolved whitelist plus active watchlist members) by name,
that equities are only held to freshness inside US trading hours, and that
the evidence capture fires before a restart on the diagnosable conditions.

No network, no process: everything runs against tmp DBs and monkeypatches.
"""
from __future__ import annotations

import sqlite3
from datetime import datetime, timezone

from market_data import alpaca_source
from ops import watchdog


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _mk_db(tmp_path, bars):
    """bars: list of (symbol, ts, source)."""
    db = tmp_path / "feed.db"
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


# --- One stale symbol among fresh ones, named --------------------------------

def test_single_stale_symbol_detected_by_name_while_others_fresh(
        tmp_path, monkeypatch):
    # THE SOL/USD shape: BTC current, SOL a day old. The old probe read the
    # newest crypto bar (BTC) and reported fresh.
    _pin(monkeypatch, ["BTC/USD", "SOL/USD"])
    db = _mk_db(tmp_path, [("BTC/USD", _now_iso(), "real_feed"),
                           ("SOL/USD", "2026-07-17T06:10:00Z", "backfill")])
    out = watchdog.feed_ok(900, db)
    assert out["fresh"] is False
    assert out["ok"] is False
    assert out["stale_symbols"] == ["SOL/USD"]
    assert out["symbols"]["BTC/USD"]["fresh"] is True
    assert out["symbols"]["SOL/USD"]["fresh"] is False


def test_symbol_with_no_bars_at_all_is_stale_by_name(tmp_path, monkeypatch):
    # Never polled and never backfilled: the exact state a dead watchlist
    # entry sits in. Detectable, named, with the reason.
    _pin(monkeypatch, ["BTC/USD", "SOL/USD"])
    db = _mk_db(tmp_path, [("BTC/USD", _now_iso(), "real_feed")])
    out = watchdog.feed_ok(900, db)
    assert out["stale_symbols"] == ["SOL/USD"]
    assert out["symbols"]["SOL/USD"]["reason"] == "no_bars"


def test_all_fresh_reads_healthy(tmp_path, monkeypatch):
    _pin(monkeypatch, ["BTC/USD", "ETH/USD"])
    db = _mk_db(tmp_path, [("BTC/USD", _now_iso(), "real_feed"),
                           ("ETH/USD", _now_iso(), "real_feed")])
    out = watchdog.feed_ok(900, db)
    assert out["fresh"] is True and out["ok"] is True
    assert out["stale_symbols"] == []


# --- Watchlist members join the checked set ----------------------------------

def _add_watchlist(db, symbol, status="active"):
    conn = sqlite3.connect(db)
    from discovery import watchlist as wl
    wl.ensure_schema(conn)
    conn.execute(
        "INSERT INTO watchlist(symbol,asset_class,added_ts,updated_ts,source,"
        "reason,sleeve_target,score,status) VALUES(?,?,?,?,?,?,?,?,?)",
        (symbol, "crypto", _now_iso(), _now_iso(), "discovery", "test",
         "quant_core", 0.6, status))
    conn.commit()
    conn.close()


def test_watchlist_member_is_checked_when_discovery_on(tmp_path, monkeypatch):
    _pin(monkeypatch, ["BTC/USD"], discovery=True)
    db = _mk_db(tmp_path, [("BTC/USD", _now_iso(), "real_feed")])
    _add_watchlist(db, "LDO/USD")
    assert watchdog.tradeable_symbols(db) == ["BTC/USD", "LDO/USD"]
    out = watchdog.feed_ok(900, db)
    # Onboarded but never polled: exactly the dead-entry condition.
    assert out["stale_symbols"] == ["LDO/USD"]
    assert out["ok"] is False


def test_watchlist_ignored_when_discovery_off(tmp_path, monkeypatch):
    _pin(monkeypatch, ["BTC/USD"], discovery=False)
    db = _mk_db(tmp_path, [("BTC/USD", _now_iso(), "real_feed")])
    _add_watchlist(db, "LDO/USD")
    # Discovery off means the engine never merges the watchlist, so holding
    # its members to freshness would alarm on symbols nobody trades.
    assert watchdog.tradeable_symbols(db) == ["BTC/USD"]
    assert watchdog.feed_ok(900, db)["ok"] is True


def test_referred_watchlist_entries_are_not_checked(tmp_path, monkeypatch):
    # referred is NOT tradeable (the engine never merges it), so it is not
    # held to freshness either.
    _pin(monkeypatch, ["BTC/USD"], discovery=True)
    db = _mk_db(tmp_path, [("BTC/USD", _now_iso(), "real_feed")])
    _add_watchlist(db, "XX/USD", status="referred")
    assert watchdog.tradeable_symbols(db) == ["BTC/USD"]


# --- Equities respect market hours -------------------------------------------

def test_equity_not_held_to_freshness_outside_rth(tmp_path, monkeypatch):
    _pin(monkeypatch, ["BTC/USD", "SPY"], rth=False)
    db = _mk_db(tmp_path, [("BTC/USD", _now_iso(), "real_feed"),
                           ("SPY", "2026-07-17T19:55:00Z", "real_feed")])
    out = watchdog.feed_ok(900, db)
    assert out["symbols"]["SPY"] == {"checked": False,
                                     "reason": "market_closed"}
    assert out["ok"] is True             # a closed market is not a stale feed


def test_stale_equity_detected_during_rth(tmp_path, monkeypatch):
    _pin(monkeypatch, ["BTC/USD", "SPY"], rth=True)
    db = _mk_db(tmp_path, [("BTC/USD", _now_iso(), "real_feed"),
                           ("SPY", "2026-07-17T19:55:00Z", "real_feed")])
    out = watchdog.feed_ok(900, db)
    assert "SPY" in out["stale_symbols"]
    assert out["ok"] is False


# --- Provenance stays per-symbol ---------------------------------------------

def test_fresh_but_synthetic_symbol_named_on_real_path(tmp_path, monkeypatch):
    _pin(monkeypatch, ["BTC/USD", "ETH/USD"], real=True)
    db = _mk_db(tmp_path, [("BTC/USD", _now_iso(), "real_feed"),
                           ("ETH/USD", _now_iso(), "synthetic")])
    out = watchdog.feed_ok(900, db)
    assert out["fresh"] is True
    assert out["non_real_symbols"] == ["ETH/USD"]
    assert out["ok"] is False


def test_status_line_names_the_stale_symbol(monkeypatch):
    h = {"engine": True, "bridge": True, "backend": True,
         "feed_fresh": False, "feed_ok": False, "feed_source": "real_feed",
         "feed_stale_symbols": ["SOL/USD"], "feed_non_real_symbols": [],
         "kill_tripped": False, "healthy": False}
    assert "SOL/USD" in watchdog._status_line(h)


# --- Evidence capture fires before a restart ---------------------------------

def test_capture_before_restart_fires_on_degraded_bridge(
        tmp_path, monkeypatch):
    monkeypatch.setenv("MAL_DIAGNOSTICS_DIR", str(tmp_path / "diag"))
    from ops import evidence
    monkeypatch.setattr(evidence, "_last_capture", {})
    monkeypatch.setattr(
        watchdog, "bridge_fd_snapshot",
        lambda: {"available": True, "bridge_pid": 4242,
                 "fd_count": 987, "socket_count": 640})
    h = {"bridge_status": "degraded", "feed_substitution": False}
    snap, note = watchdog.capture_before_restart(h)
    assert snap["fd_count"] == 987
    assert "987" in note and "640" in note
    records = list((tmp_path / "diag").glob("bridge_degraded-*.json"))
    assert len(records) == 1


def test_capture_before_restart_fires_on_feed_substitution(
        tmp_path, monkeypatch):
    monkeypatch.setenv("MAL_DIAGNOSTICS_DIR", str(tmp_path / "diag"))
    from ops import evidence
    monkeypatch.setattr(evidence, "_last_capture", {})
    monkeypatch.setattr(
        watchdog, "bridge_fd_snapshot",
        lambda: {"available": False, "reason": "no bridge pid in engine.lock"})
    h = {"bridge_status": "ok", "feed_substitution": True}
    snap, note = watchdog.capture_before_restart(h)
    assert "captured before restart" in note
    assert list((tmp_path / "diag").glob("feed_substitution-*.json"))


def test_capture_before_restart_noop_when_neither_condition(monkeypatch):
    called = []
    monkeypatch.setattr(watchdog, "bridge_fd_snapshot",
                        lambda: called.append(True) or {})
    snap, note = watchdog.capture_before_restart(
        {"bridge_status": "down", "feed_substitution": False})
    assert snap is None and note == ""
    assert called == []                  # a plain crash captures nothing
