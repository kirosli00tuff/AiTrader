"""Tests for the dynamic watchlist and the curated universe.

The watchlist is event-sourced so the deferred react layer can add and remove
without a rewrite. Two things are asserted hard:
  * discovery adds, and staleness / broken theses prune.
  * a NOT-YET-ENABLED source is REFUSED, not silently applied. That is what keeps
    the react layer off until it is deliberately built and gated.
"""
from __future__ import annotations

import os
import sqlite3
from datetime import datetime, timedelta, timezone

import yaml

from discovery import universe, watchlist

NOW = datetime(2026, 7, 15, 12, 0, tzinfo=timezone.utc)


def _conn(tmp_path) -> sqlite3.Connection:
    c = sqlite3.connect(os.path.join(str(tmp_path), "w.db"))
    watchlist.ensure_schema(c)
    return c


def _iso(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


# --- add --------------------------------------------------------------------

def test_discovery_adds_a_survivor(tmp_path):
    c = _conn(tmp_path)
    r = watchlist.add_from_discovery(c, "AAPL", reason="discovery buy 0.8",
                                     sleeve_target="quant_core", score=0.8,
                                     asset_class="equity", ts=_iso(NOW))
    assert r == {"applied": True, "reason": "added"}
    rows = watchlist.active(c)
    assert len(rows) == 1
    assert rows[0]["symbol"] == "AAPL"
    assert rows[0]["sleeve_target"] == "quant_core"
    assert rows[0]["source"] == "discovery"
    assert rows[0]["added_ts"] == _iso(NOW)


def test_readd_refreshes_without_losing_the_original_add_date(tmp_path):
    c = _conn(tmp_path)
    watchlist.add_from_discovery(c, "AAPL", reason="first", score=0.5,
                                 ts=_iso(NOW))
    later = NOW + timedelta(hours=5)
    watchlist.add_from_discovery(c, "AAPL", reason="second", score=0.9,
                                 ts=_iso(later))

    rows = watchlist.active(c)
    assert len(rows) == 1                    # refreshed in place, not duplicated
    assert rows[0]["added_ts"] == _iso(NOW)  # when it FIRST appeared survives
    assert rows[0]["updated_ts"] == _iso(later)
    assert rows[0]["score"] == 0.9
    assert rows[0]["reason"] == "second"


def test_active_symbols_filters_by_sleeve(tmp_path):
    c = _conn(tmp_path)
    watchlist.add_from_discovery(c, "AAPL", reason="r",
                                 sleeve_target="quant_core")
    watchlist.add_from_discovery(c, "MSFT", reason="r",
                                 sleeve_target="research_satellite")
    assert watchlist.active_symbols(c, "quant_core") == ["AAPL"]
    assert watchlist.active_symbols(c, "research_satellite") == ["MSFT"]
    # Both sleeves draw from one list.
    assert watchlist.active_symbols(c) == ["AAPL", "MSFT"]


def test_unknown_sleeve_target_falls_back_to_quant_core(tmp_path):
    c = _conn(tmp_path)
    watchlist.add_from_discovery(c, "AAPL", reason="r", sleeve_target="nonsense")
    assert watchlist.active(c)[0]["sleeve_target"] == "quant_core"


# --- prune ------------------------------------------------------------------

def test_prune_stale_removes_only_what_went_stale(tmp_path):
    c = _conn(tmp_path)
    watchlist.add_from_discovery(c, "OLD", reason="r",
                                 ts=_iso(NOW - timedelta(hours=72)))
    watchlist.add_from_discovery(c, "FRESH", reason="r",
                                 ts=_iso(NOW - timedelta(hours=2)))

    out = watchlist.prune_stale(c, stale_hours=48, now=NOW)
    assert out["pruned"] == ["OLD"]
    assert watchlist.active_symbols(c) == ["FRESH"]


def test_stale_symbols_is_a_pure_read(tmp_path):
    c = _conn(tmp_path)
    watchlist.add_from_discovery(c, "OLD", reason="r",
                                 ts=_iso(NOW - timedelta(hours=72)))
    assert watchlist.stale_symbols(c, 48, NOW) == ["OLD"]
    # Reading did not remove it.
    assert watchlist.active_symbols(c) == ["OLD"]


def test_prune_broken_thesis(tmp_path):
    c = _conn(tmp_path)
    watchlist.add_from_discovery(c, "NVDA", reason="r", ts=_iso(NOW))
    r = watchlist.prune_broken_thesis(c, "NVDA", reason="thesis invalidated",
                                      ts=_iso(NOW))
    assert r["applied"] is True
    assert watchlist.active_symbols(c) == []

    # The row survives as a soft delete, so the operator sees what left and why.
    row = c.execute("SELECT status, removed_reason FROM watchlist "
                    "WHERE symbol='NVDA'").fetchone()
    assert row == ("removed", "thesis invalidated")


def test_removing_something_not_on_the_list_is_reported_not_silent(tmp_path):
    c = _conn(tmp_path)
    r = watchlist.prune_broken_thesis(c, "GHOST")
    assert r == {"applied": False, "reason": "not_on_watchlist"}


def test_readd_after_prune_reactivates(tmp_path):
    c = _conn(tmp_path)
    watchlist.add_from_discovery(c, "AAPL", reason="r", ts=_iso(NOW))
    watchlist.prune_broken_thesis(c, "AAPL", ts=_iso(NOW))
    assert watchlist.active_symbols(c) == []

    watchlist.add_from_discovery(c, "AAPL", reason="back", ts=_iso(NOW))
    assert watchlist.active_symbols(c) == ["AAPL"]
    row = c.execute("SELECT removed_ts, removed_reason FROM watchlist "
                    "WHERE symbol='AAPL'").fetchone()
    assert row == (None, None)  # the removal is cleared, not left dangling


def test_enforce_max_size_keeps_the_strongest(tmp_path):
    c = _conn(tmp_path)
    for i, score in enumerate([0.9, 0.5, 0.7, 0.2, 0.8]):
        watchlist.add_from_discovery(c, f"S{i}", reason="r", score=score,
                                     ts=_iso(NOW))

    out = watchlist.enforce_max_size(c, max_size=3, ts=_iso(NOW))
    assert out["count"] == 2
    # The watchlist is the NARROW end of the funnel: the strongest survive.
    assert sorted(watchlist.active_symbols(c)) == ["S0", "S2", "S4"]
    assert sorted(out["dropped"]) == ["S1", "S3"]


# --- the react-layer seam ---------------------------------------------------

def test_a_reserved_source_is_refused_and_journalled(tmp_path, monkeypatch):
    """The gated react layer parses, is journalled, and is REFUSED while OFF.

    The off-ness is stated here rather than inherited from the machine. This test
    read the live .control/controls.json through the lazy
    adaptive_settings.watchlist_shaping_enabled() call inside _shaping_enabled,
    so it went red the moment a real operator turned watchlist shaping on: it
    reported a refusal regression when the source had simply, correctly, been
    enabled. A test of "refused while off" has to pin off.
    """
    monkeypatch.setattr(watchlist, "_shaping_enabled", lambda: False)
    c = _conn(tmp_path)
    r = watchlist.apply_event(c, watchlist.WatchlistEvent(
        action="add", symbol="AAPL", source="adaptive_react",
        reason="breaking headline", ts=_iso(NOW)))

    assert r == {"applied": False, "reason": "source_not_enabled"}
    assert watchlist.active_symbols(c) == []
    # Refused, but visible: a silently dropped event is worse than a loud one.
    events = watchlist.recent_events(c)
    assert len(events) == 1
    assert events[0]["source"] == "adaptive_react"
    assert events[0]["applied"] is False


def test_an_unknown_source_is_refused(tmp_path):
    c = _conn(tmp_path)
    r = watchlist.apply_event(c, watchlist.WatchlistEvent(
        action="add", symbol="AAPL", source="whoever", ts=_iso(NOW)))
    assert r["applied"] is False
    assert r["reason"] == "unknown_source"


def test_adaptive_react_is_gated_not_unconditional():
    """The react layer GRADUATED from reserved to gated (2026-07-16).

    It used to sit in RESERVED_SOURCES and be refused unconditionally. It is now
    a real source, but a GATED one: accepted only while the operator's
    adaptive_watchlist_shaping_enabled flag is on, which ships false. The
    invariant that matters did not change, and is re-asserted here and in
    tests/test_adaptive_shaping.py: under the shipped config an adaptive_react
    event is still refused with source_not_enabled.

    It is deliberately NOT in ACTIVE_SOURCES: that tuple is the unconditional
    allowlist, and a source that can move the watchlist on a headline must never
    be unconditional.
    """
    assert watchlist.ACTIVE_SOURCES == ("discovery", "prune")
    assert "adaptive_react" in watchlist.GATED_SOURCES
    assert "adaptive_react" not in watchlist.ACTIVE_SOURCES
    assert "adaptive_react" not in watchlist.RESERVED_SOURCES
    # `manual` stays reserved: no producer, refused, still a seam.
    assert "manual" in watchlist.RESERVED_SOURCES
    # An adaptive add can only ever be a REFERRAL, never a live entry. This is
    # what makes "aggressive entry always goes through the funnel" structural:
    # the status is derived from the source, so no caller can request `active`.
    assert watchlist._entry_status_for("adaptive_react") == "referred"
    assert watchlist._entry_status_for("discovery") == "active"


def test_invalid_events_are_refused(tmp_path):
    c = _conn(tmp_path)
    assert watchlist.apply_event(c, watchlist.WatchlistEvent(
        action="explode", symbol="AAPL",
        source="discovery"))["reason"] == "invalid_action"
    assert watchlist.apply_event(c, watchlist.WatchlistEvent(
        action="add", symbol="", source="discovery"))["reason"] == "no_symbol"


def test_recent_events_shows_the_list_living(tmp_path):
    c = _conn(tmp_path)
    watchlist.add_from_discovery(c, "AAPL", reason="found", ts=_iso(NOW))
    watchlist.prune_broken_thesis(c, "AAPL", reason="broke", ts=_iso(NOW))
    events = watchlist.recent_events(c)
    assert [e["action"] for e in events] == ["remove", "add"]  # newest first
    assert all(e["applied"] for e in events)


# --- universe ---------------------------------------------------------------

def _cfg_with_universe(tmp_path, crypto: str, active_max: int = 3) -> str:
    os.makedirs(str(tmp_path), exist_ok=True)
    p = os.path.join(str(tmp_path), "u.yaml")
    with open(p, "w", encoding="utf-8") as f:
        yaml.safe_dump({"discovery": {"crypto_universe": crypto,
                                      "equity_universe": "AAPL,MSFT",
                                      "crypto_active_max": active_max}}, f)
    return p


def _seed_bars(db: str, rows: list[tuple[str, float, float]]) -> None:
    c = sqlite3.connect(db)
    c.execute("CREATE TABLE IF NOT EXISTS bars (id INTEGER PRIMARY KEY "
              "AUTOINCREMENT, venue TEXT, symbol TEXT, timeframe TEXT, "
              "timestamp TEXT, open REAL, high REAL, low REAL, close REAL, "
              "volume REAL)")
    for symbol, close, volume in rows:
        c.execute("INSERT INTO bars(venue,symbol,timeframe,timestamp,open,high,"
                  "low,close,volume) VALUES('alpaca',?,'5min',?,?,?,?,?,?)",
                  (symbol, _iso(NOW - timedelta(hours=1)), close, close, close,
                   close, volume))
    c.commit()
    c.close()


def test_is_crypto():
    assert universe.is_crypto("BTC/USD")
    assert universe.is_crypto("BTC-USD")
    assert not universe.is_crypto("AAPL")


def test_crypto_refresh_ranks_by_dollar_volume(tmp_path):
    db = os.path.join(str(tmp_path), "u.db")
    # Config order is A,B,C but dollar volume says C > A > B.
    _seed_bars(db, [("A/USD", 10.0, 100.0),    # 1000
                    ("B/USD", 1.0, 50.0),      # 50
                    ("C/USD", 100.0, 100.0)])  # 10000
    cfg = _cfg_with_universe(tmp_path, "A/USD,B/USD,C/USD", active_max=3)

    out = universe.refresh_active_crypto(db, cfg, NOW)
    assert out["ranked_by"] == "volume"
    assert out["active"] == ["C/USD", "A/USD", "B/USD"]
    assert out["with_volume"] == 3


def test_crypto_refresh_applies_the_active_cap(tmp_path):
    db = os.path.join(str(tmp_path), "u.db")
    _seed_bars(db, [("A/USD", 10.0, 100.0), ("B/USD", 1.0, 50.0),
                    ("C/USD", 100.0, 100.0)])
    cfg = _cfg_with_universe(tmp_path, "A/USD,B/USD,C/USD", active_max=2)
    out = universe.refresh_active_crypto(db, cfg, NOW)
    assert out["active"] == ["C/USD", "A/USD"]


def test_no_volume_evidence_keeps_config_order(tmp_path):
    """Absent bars is NOT evidence of zero liquidity, so config order holds."""
    db = os.path.join(str(tmp_path), "empty.db")
    _seed_bars(db, [])
    cfg = _cfg_with_universe(tmp_path, "A/USD,B/USD,C/USD", active_max=2)
    out = universe.refresh_active_crypto(db, cfg, NOW)
    assert out["ranked_by"] == "config_order"
    assert out["active"] == ["A/USD", "B/USD"]


def test_symbols_with_volume_rank_above_symbols_without(tmp_path):
    db = os.path.join(str(tmp_path), "u.db")
    _seed_bars(db, [("C/USD", 100.0, 100.0)])  # only C has evidence
    cfg = _cfg_with_universe(tmp_path, "A/USD,B/USD,C/USD", active_max=3)
    out = universe.refresh_active_crypto(db, cfg, NOW)
    assert out["active"][0] == "C/USD"
    assert set(out["active"][1:]) == {"A/USD", "B/USD"}


def test_unreadable_db_degrades_to_config_order(tmp_path):
    cfg = _cfg_with_universe(tmp_path, "A/USD,B/USD")
    out = universe.refresh_active_crypto(
        os.path.join(str(tmp_path), "does-not-exist.db"), cfg, NOW)
    # The universe refresh must never raise: discovery is advisory.
    assert out["active"] == ["A/USD", "B/USD"]
    assert out["ranked_by"] == "config_order"


def test_equities_are_a_stable_curated_list(tmp_path):
    cfg = _cfg_with_universe(tmp_path, "A/USD")
    assert universe.active_equities(cfg) == ["AAPL", "MSFT"]


def test_universe_for_dispatches_by_asset_class(tmp_path):
    db = os.path.join(str(tmp_path), "u.db")
    _seed_bars(db, [])
    cfg = _cfg_with_universe(tmp_path, "A/USD,B/USD", active_max=5)
    assert universe.universe_for("equity", db, cfg, NOW) == ["AAPL", "MSFT"]
    assert universe.universe_for("crypto", db, cfg, NOW) == ["A/USD", "B/USD"]
    assert universe.universe_for("nonsense", db, cfg, NOW) == []


def test_shipped_universe_meets_the_spec():
    """The real config: at least 100 equities, crypto capped at 50."""
    from discovery import settings
    assert len(settings.equity_universe(None)) >= 100
    assert settings.crypto_active_max(None) <= 50
    # The broader crypto list must be able to fill the active set.
    assert len(settings.crypto_universe(None)) >= settings.crypto_active_max(None)
