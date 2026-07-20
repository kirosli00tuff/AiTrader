"""Recency-scoped substitution, startup grace, onboarding-incomplete, and the
remediation loop guard.

The 2026-07-20 failure is the spec. The stack started clean, and seconds later
the watchdog read the NEWEST bars in the table (synthetic rows left over from
the 2026-07-19 outage), concluded a live feed substitution, and stopped the
whole stack before it could fetch a single live bar. Every start died the same
way: a remediation loop with no exit. Two aggravators: MANA/USD and RUNE/USD
sat on the watchlist with zero bars ever and counted as stale, and the
substitution check considered the newest row of ANY age.

These tests pin the four guards: substitution is judged only on bars inside
the recency window, feed conditions inside the startup grace are logged but
not remediated, a zero-bar symbol is an incomplete onboarding rather than a
stale feed, and a condition recurring right after a restart escalates to
notify-and-hold. Both directions are proven: the observed historical shape
does NOT stop the stack, and a genuine in-window substitution after the grace
still does.

No network, no process: everything runs against tmp DBs and monkeypatches.
The kill-request file is never touched and the kill switch is never resumed.
"""
from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta, timezone

import pytest

from market_data import alpaca_source
from ops import watchdog


@pytest.fixture(autouse=True)
def _isolated_state(tmp_path, monkeypatch):
    """Own loop-guard state file per test."""
    monkeypatch.setenv("MAL_RUN_DIR", str(tmp_path / "run"))


def _ago(seconds: int) -> str:
    dt = datetime.now(timezone.utc) - timedelta(seconds=seconds)
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


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


def _add_watchlist(db, symbol, status="active"):
    conn = sqlite3.connect(db)
    from discovery import watchlist as wl
    wl.ensure_schema(conn)
    conn.execute(
        "INSERT INTO watchlist(symbol,asset_class,added_ts,updated_ts,source,"
        "reason,sleeve_target,score,status) VALUES(?,?,?,?,?,?,?,?,?)",
        (symbol, "crypto", _ago(0), _ago(0), "discovery", "test",
         "quant_core", 0.6, status))
    conn.commit()
    conn.close()


def _pin(monkeypatch, symbols, *, real=True, discovery=False, rth=True):
    monkeypatch.setattr(watchdog.stack, "whitelist", lambda: list(symbols))
    monkeypatch.setattr(watchdog, "_real_feed_mode", lambda: real)
    monkeypatch.setattr(watchdog, "_discovery_enabled", lambda: discovery)
    monkeypatch.setattr(watchdog, "_equity_market_open", lambda: rth)


def _health(*, degraded=False, substitution=False, stale=False, kill=False,
            engine=True, bridge=True, backend=True):
    healthy = (engine and bridge and backend and not degraded
               and not substitution and not stale)
    return {"engine": engine, "bridge": bridge and not degraded,
            "bridge_status": "degraded" if degraded else
            ("ok" if bridge else "down"),
            "bridge_degraded": ["fd_headroom"] if degraded else [],
            "backend": backend, "feed_fresh": not stale,
            "feed_source": "real_feed",
            "feed_ok": not substitution and not stale,
            "feed_stale_symbols": ["LDO/USD"] if stale else [],
            "feed_non_real_symbols": ["BTC/USD"] if substitution else [],
            "feed_symbol_unavailable": [], "feed_out_of_window_non_real": [],
            "feed_substitution": substitution, "kill_tripped": kill,
            "healthy": healthy}


def _wire(monkeypatch, *, health, running=True, age=None, posts=None,
          notes=None):
    """Wire run_once's collaborators: recorded supervisor posts, recorded
    notifications, quiet evidence capture, a self-heal recorder, and a pinned
    engine age for the grace period."""
    posts = posts if posts is not None else []
    notes = notes if notes is not None else []

    def fake_post(path, timeout=30):
        posts.append(path)
        if path == "/engine/stop":
            return {"ok": True, "state": "not_running"}
        return {"ok": True, "state": "starting"}

    monkeypatch.setattr(watchdog, "check_health", lambda cfg=None: health)
    monkeypatch.setattr(watchdog, "_supervisor_post", fake_post)
    monkeypatch.setattr(watchdog.stack, "stack_running",
                        lambda: {"running": running})
    monkeypatch.setattr(watchdog.stack, "self_heal", lambda: {"stopped": []})
    monkeypatch.setattr(watchdog, "notify",
                        lambda msg, cfg=None, title="": notes.append(msg)
                        or True)
    monkeypatch.setattr(watchdog, "capture_before_restart",
                        lambda h: (None, ""))
    monkeypatch.setattr(watchdog, "_engine_age_seconds", lambda: age)
    return posts, notes


# --- TASK 1: substitution considers only bars inside the recency window ------

def test_out_of_window_synthetic_bar_is_not_substitution(tmp_path,
                                                         monkeypatch):
    # The exact 2026-07-20 shape: the newest LDO/USD row is a synthetic
    # leftover from a PRIOR run, two hours old (older backfill rows make it
    # tradeable, matching the real LDO). Historical evidence, logged
    # out-of-window. The symbol is still STALE, which is the correct question
    # to raise about it: freshness, not substitution.
    _pin(monkeypatch, ["BTC/USD", "LDO/USD"])
    db = _mk_db(tmp_path, [("BTC/USD", _ago(60), "backfill"),
                           ("LDO/USD", _ago(86400), "backfill"),
                           ("LDO/USD", _ago(7200), "synthetic")])
    out = watchdog.feed_ok(900, db, recency_window_seconds=900)
    assert out["non_real_symbols"] == []
    assert out["out_of_window_non_real"] == ["LDO/USD"]
    assert out["symbols"]["LDO/USD"]["provenance"] == "out_of_window"
    assert out["stale_symbols"] == ["LDO/USD"]
    assert out["real"] is True


def test_in_window_synthetic_bar_is_substitution(tmp_path, monkeypatch):
    # A synthetic bar RECENT enough to reflect the running process, on a
    # symbol WITH real history, is the genuine substitution state and must
    # still be detected, even while BTC is served on time.
    _pin(monkeypatch, ["BTC/USD", "LDO/USD"])
    db = _mk_db(tmp_path, [("BTC/USD", _ago(60), "backfill"),
                           ("LDO/USD", _ago(86400), "backfill"),
                           ("LDO/USD", _ago(60), "synthetic")])
    out = watchdog.feed_ok(900, db, recency_window_seconds=900)
    assert out["non_real_symbols"] == ["LDO/USD"]
    assert out["out_of_window_non_real"] == []
    assert out["ok"] is False


def test_check_health_substitution_respects_the_window(tmp_path, monkeypatch):
    _pin(monkeypatch, ["LDO/USD"])
    old = _mk_db(tmp_path, [("LDO/USD", _ago(86400), "backfill"),
                            ("LDO/USD", _ago(7200), "synthetic")])
    monkeypatch.setattr(watchdog, "_db_path", lambda: old)
    monkeypatch.setattr(watchdog, "bridge_state",
                        lambda: {"reachable": True, "status": "ok",
                                 "degraded": [], "fd_count": 40})
    monkeypatch.setattr(watchdog.stack, "http_ok", lambda *a, **k: True)
    monkeypatch.setattr(watchdog.stack, "stack_running",
                        lambda: {"running": True})
    monkeypatch.setattr(watchdog, "kill_tripped", lambda: False)
    h = watchdog.check_health({"bar_staleness_seconds": 900,
                               "substitution_recency_window_seconds": 900})
    assert h["feed_substitution"] is False
    assert h["feed_out_of_window_non_real"] == ["LDO/USD"]


# --- TASK 3: no real bar history is symbol_unavailable, never stale ----------

def test_zero_bar_symbol_is_not_counted_stale(tmp_path, monkeypatch):
    _pin(monkeypatch, ["BTC/USD", "MANA/USD"])
    db = _mk_db(tmp_path, [("BTC/USD", _ago(60), "backfill")])
    out = watchdog.feed_ok(900, db)
    assert out["stale_symbols"] == []
    assert out["unavailable_symbols"] == ["MANA/USD"]
    assert out["fresh"] is True and out["ok"] is True


def test_symbol_unavailable_named_in_status_line():
    h = {"engine": True, "bridge": True, "backend": True, "feed_fresh": True,
         "feed_ok": True, "feed_source": "real_feed",
         "feed_stale_symbols": [], "feed_non_real_symbols": [],
         "feed_symbol_unavailable": ["MANA/USD", "RUNE/USD"],
         "kill_tripped": False, "healthy": True}
    line = watchdog._status_line(h)
    assert "symbol_unavailable" in line and "MANA/USD" in line


# --- TASK 2: the startup grace suppresses feed remediation, then expires -----

def test_grace_suppresses_feed_remediation_then_expires(monkeypatch):
    posts, notes = _wire(monkeypatch, health=_health(substitution=True),
                         age=10)
    res = watchdog.run_once({})
    assert res["action"] == "grace_observed"
    assert posts == [] and notes == []          # observed and logged only
    # Same condition past the grace: remediation proceeds as designed.
    posts2, notes2 = _wire(monkeypatch, health=_health(substitution=True),
                           age=1200)
    res2 = watchdog.run_once({})
    assert res2["action"] == "restarted"
    assert posts2 == ["/engine/stop", "/engine/start"]


def test_grace_never_suppresses_a_degraded_bridge(monkeypatch):
    # TASK 6: a genuine degraded bridge still triggers the existing single
    # restart, at any engine age.
    posts, _ = _wire(monkeypatch, health=_health(degraded=True), age=10)
    res = watchdog.run_once({})
    assert res["action"] == "restarted"
    assert posts == ["/engine/stop", "/engine/start"]


def test_unknown_engine_age_reads_past_grace(monkeypatch):
    # An unprovable grace must never suppress detection forever.
    posts, _ = _wire(monkeypatch, health=_health(substitution=True), age=None)
    assert watchdog.run_once({})["action"] == "restarted"
    assert posts == ["/engine/stop", "/engine/start"]


# --- TASK 4: remediation must not loop ---------------------------------------

def test_same_condition_after_restart_escalates_to_hold(monkeypatch):
    posts, notes = _wire(monkeypatch, health=_health(substitution=True))
    assert watchdog.run_once({})["action"] == "restarted"
    assert posts == ["/engine/stop", "/engine/start"]
    res = watchdog.run_once({})
    assert res["action"] == "hold"
    assert res["reason"] == "remediation_loop"
    assert posts == ["/engine/stop", "/engine/start"]  # no second stop, ever
    hold_notes = [n for n in notes if "REMEDIATION HOLD" in n]
    assert len(hold_notes) == 1
    # A third cycle holds silently (renotify only after the hold window).
    assert watchdog.run_once({})["action"] == "hold"
    assert len([n for n in notes if "REMEDIATION HOLD" in n]) == 1


def test_hold_releases_on_healthy_and_notifies_recovery(monkeypatch):
    posts, notes = _wire(monkeypatch, health=_health(substitution=True))
    watchdog.run_once({})
    watchdog.run_once({})                        # now holding
    _wire(monkeypatch, health=_health(), posts=posts, notes=notes)
    res = watchdog.run_once({})
    assert res["action"] == "none"
    assert any("Recovered" in n for n in notes)
    assert watchdog._load_state() == {}


def test_a_different_condition_still_gets_its_single_restart(monkeypatch):
    posts, _ = _wire(monkeypatch, health=_health(substitution=True))
    watchdog.run_once({})
    posts2, _ = _wire(monkeypatch, health=_health(degraded=True))
    res = watchdog.run_once({})
    assert res["action"] == "restarted"          # new failure, own restart
    assert posts2 == ["/engine/stop", "/engine/start"]


def test_restart_rate_cap_holds_across_conditions(monkeypatch):
    # An A/B/A/B alternation evades the same-condition check; the hourly cap
    # (max_restarts_per_hour, wired here) catches it.
    import time as _t
    now = _t.time()
    watchdog._save_state({"condition": "bridge_down", "holding": False,
                          "attempts": 3, "last_restart_ts": now - 2400,
                          "restart_history": [now - 2400, now - 1200,
                                              now - 600],
                          "last_hold_notify_ts": 0.0})
    posts, notes = _wire(monkeypatch, health=_health(degraded=True))
    res = watchdog.run_once({})
    assert res["action"] == "hold"
    assert res["reason"] == "restart_rate_cap"
    assert posts == []
    assert any("REMEDIATION HOLD" in n for n in notes)


def test_failed_restart_attempts_also_escalate(monkeypatch):
    posts, notes = _wire(monkeypatch, health=_health(substitution=True))
    monkeypatch.setattr(watchdog, "attempt_restart",
                        lambda: {"restarted": False, "detail": "refused",
                                 "healed": {}})
    assert watchdog.run_once({})["action"] == "restart_failed"
    res = watchdog.run_once({})
    assert res["action"] == "hold"               # a failing restart loops too


def test_kill_trip_during_hold_is_never_restarted(monkeypatch):
    posts, notes = _wire(monkeypatch, health=_health(substitution=True))
    watchdog.run_once({})
    watchdog.run_once({})                        # holding
    _wire(monkeypatch, health=_health(substitution=True, kill=True),
          posts=posts, notes=notes)
    res = watchdog.run_once({})
    assert res["action"] == "kill_notified"
    assert posts == ["/engine/stop", "/engine/start"]  # from the first cycle
    assert any("Manual resume required" in n for n in notes)


# --- TASK 5: both directions against the observed 2026-07-20 failure ---------

def _wire_end_to_end(monkeypatch, db, *, age):
    posts, notes = [], []

    def fake_post(path, timeout=30):
        posts.append(path)
        if path == "/engine/stop":
            return {"ok": True, "state": "not_running"}
        return {"ok": True, "state": "starting"}

    monkeypatch.setattr(watchdog, "_db_path", lambda: db)
    monkeypatch.setattr(watchdog, "bridge_state",
                        lambda: {"reachable": True, "status": "ok",
                                 "degraded": [], "fd_count": 40})
    monkeypatch.setattr(watchdog.stack, "http_ok", lambda *a, **k: True)
    monkeypatch.setattr(watchdog.stack, "stack_running",
                        lambda: {"running": True})
    monkeypatch.setattr(watchdog.stack, "self_heal", lambda: {"stopped": []})
    monkeypatch.setattr(watchdog, "kill_tripped", lambda: False)
    monkeypatch.setattr(watchdog, "_supervisor_post", fake_post)
    monkeypatch.setattr(watchdog, "notify",
                        lambda msg, cfg=None, title="": notes.append(msg)
                        or True)
    monkeypatch.setattr(watchdog, "capture_before_restart",
                        lambda h: (None, ""))
    monkeypatch.setattr(watchdog, "_engine_age_seconds", lambda: age)
    return posts, notes


def test_observed_20260720_shape_does_not_stop_a_fresh_stack(tmp_path,
                                                             monkeypatch):
    # Reproduction of the live 2026-07-20 kill: six symbols receive real bars
    # on time, MANA/USD and RUNE/USD sit on the watchlist with nothing but
    # IN-WINDOW fabricated synthetic bars (the engine walked them at the same
    # timestamps as the real bars). The stack-level substitution condition
    # must NOT fire: those symbols have no real history, so they are
    # symbol_unavailable, contained, and the stack keeps trading. Well past
    # the startup grace, deliberately: containment must hold on its own, not
    # lean on the grace.
    _pin(monkeypatch,
         ["BTC/USD", "ETH/USD", "SPY", "QQQ"], discovery=True, rth=False)
    db = _mk_db(tmp_path, [("BTC/USD", _ago(60), "real_feed"),
                           ("ETH/USD", _ago(60), "real_feed"),
                           ("LDO/USD", _ago(86400), "backfill"),
                           ("LDO/USD", _ago(60), "real_feed"),
                           ("MANA/USD", _ago(60), "synthetic"),
                           ("RUNE/USD", _ago(60), "synthetic")])
    for sym in ("LDO/USD", "MANA/USD", "RUNE/USD"):
        _add_watchlist(db, sym)
    posts, notes = _wire_end_to_end(monkeypatch, db, age=5000)
    res = watchdog.run_once({})
    h = res["health"]
    assert h["feed_substitution"] is False       # the incident's wrong verdict
    assert h["feed_symbol_unavailable"] == ["MANA/USD", "RUNE/USD"]
    assert h["feed_non_real_symbols"] == []      # never share the alarm
    assert h["feed_serving"] is True
    assert h["healthy"] is True
    assert res["action"] == "none"               # the stack keeps trading
    assert posts == []                           # /engine/stop never sent
    assert notes == []


def test_genuine_live_substitution_after_grace_still_remediates(tmp_path,
                                                                monkeypatch):
    # The other direction: a symbol WITH real history whose in-window newest
    # bar is synthetic, past the grace, is a real substitution and triggers
    # the designed stop-then-start. ETH serving on time does NOT weaken it:
    # substitution outranks the serving predicate.
    _pin(monkeypatch, ["BTC/USD", "ETH/USD"])
    db = _mk_db(tmp_path, [("BTC/USD", _ago(86400), "backfill"),
                           ("BTC/USD", _ago(60), "synthetic"),
                           ("ETH/USD", _ago(60), "real_feed")])
    posts, notes = _wire_end_to_end(monkeypatch, db, age=2000)
    res = watchdog.run_once({})
    assert res["health"]["feed_substitution"] is True
    assert res["health"]["feed_serving"] is True  # served, and still broken
    assert res["action"] == "restarted"
    assert posts == ["/engine/stop", "/engine/start"]
    assert any("Restarted" in n for n in notes)
