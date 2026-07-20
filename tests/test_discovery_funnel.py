"""Tests for the discovery funnel: narrowing, cost ceilings, and who spends what.

The load-bearing claims, each asserted here:
  * Stage A spends ZERO LLM tokens over the whole universe.
  * The Haiku gate runs ONLY on Stage-A finalists, never the universe.
  * The council runs ONLY on Stage-B survivors, never the finalists.
  * Per-stage ceilings and the separate daily budget cap council calls.
  * Every dropped instrument records its stage and reason.
  * With the flags off, nothing runs at all.

No network and no real provider: the gate and the evaluator are counting spies,
which is what makes "spends no tokens" a real assertion rather than a claim.
"""
from __future__ import annotations

import os
import sqlite3
from datetime import datetime, timedelta, timezone

import pytest
import yaml

from discovery import funnel, run, settings, store

NOW = datetime(2026, 7, 15, 15, 0, tzinfo=timezone.utc)  # a Wednesday, US RTH


# --- helpers ----------------------------------------------------------------

def _write_cfg(tmp_path, **discovery) -> str:
    """Write a temp config with a discovery block. Returns the path.

    config_access caches per path and each test gets a unique tmp_path, so no
    cache clearing is needed between tests.
    """
    base = {
        "discovery_enabled": True,
        "long_term_sleeve_enabled": False,
        "crypto_universe": "BTC/USD,ETH/USD,SOL/USD",
        "equity_universe": "AAPL,MSFT,NVDA",
        "crypto_active_max": 50,
        "max_finalists": 12,
        "max_survivors": 5,
        "max_council_calls_per_pass": 5,
        "discovery_daily_council_budget": 12,
        "discovery_est_cost_per_call_usd": 0.04,
        "crypto_interval_minutes": 60,
        "equity_interval_minutes": 60,
        "prescreen_min_score": 0.15,
        "watchlist_max_size": 40,
        "watchlist_stale_hours": 48,
    }
    base.update(discovery)
    os.makedirs(tmp_path, exist_ok=True)
    p = os.path.join(str(tmp_path), "cfg.yaml")
    with open(p, "w", encoding="utf-8") as f:
        yaml.safe_dump({"discovery": base,
                        "sleeves": {"research_conviction_threshold": 0.70},
                        "council": {"council_min_confidence": 0.6}}, f)
    return p


class SpyGate:
    """A Haiku-gate stand-in that records exactly which symbols it saw."""

    def __init__(self, reject: set[str] | None = None) -> None:
        self.seen: list[str] = []
        self.reject = reject or set()

    def should_review(self, state):
        symbol = state["symbol"]
        self.seen.append(symbol)
        rejected = symbol in self.reject

        class _D:
            proceed = not rejected
            reason = "too quiet" if rejected else "worth a look"
        return _D()


class SpyEvaluator:
    """A four-level-evaluation stand-in that records which symbols it scored."""

    def __init__(self, conviction: float = 0.8) -> None:
        self.seen: list[str] = []
        self.conviction = conviction

    def __call__(self, symbol: str) -> dict:
        self.seen.append(symbol)
        return {"symbol": symbol, "verdict": "buy", "direction": "long",
                "conviction": self.conviction, "edge": 0.05, "agreement": 3,
                "size_pct": 0.4, "horizon": "days", "rationale": "spy"}


def _snap(symbol: str, *, change_pct: float = 3.0, price: float = 100.0,
          high: float = 103.0, low: float = 99.0, **kw) -> dict:
    s = {"symbol": symbol, "price": price, "change_pct": change_pct,
         "high": high, "low": low, "open": 100.0, "prev_close": 100.0}
    s.update(kw)
    return s


# --- Stage A: free ----------------------------------------------------------

def test_prescreen_scores_movement_over_quiet():
    loud, _ = funnel.prescreen_score(
        _snap("AAPL", change_pct=5.0, high=106.0, low=100.0))
    quiet, _ = funnel.prescreen_score(
        _snap("KO", change_pct=0.05, high=100.1, low=99.9))
    assert loud > quiet
    assert 0.0 <= quiet <= loud <= 1.0


def test_prescreen_score_needs_a_price():
    score, detail = funnel.prescreen_score(_snap("X", price=0.0))
    assert score == 0.0
    assert detail["reason"] == "no price"


def test_prescreen_sentiment_scores_deviation_not_direction():
    """Strongly bearish news is as interesting as strongly bullish."""
    bull, _ = funnel.prescreen_score(_snap("A", sentiment_score=0.95))
    bear, _ = funnel.prescreen_score(_snap("A", sentiment_score=0.05))
    neutral, _ = funnel.prescreen_score(_snap("A", sentiment_score=0.5))
    assert bull == bear
    assert bull > neutral


def test_prescreen_drops_below_floor_and_beyond_rank():
    snaps = [_snap(f"S{i}", change_pct=5.0 - i * 0.1) for i in range(10)]
    snaps.append(_snap("QUIET", change_pct=0.0, high=100.01, low=100.0))
    finalists, drops = funnel.prescreen(snaps, max_finalists=3, min_score=0.15)

    assert len(finalists) == 3
    reasons = {d.symbol: d.reason for d in drops}
    assert reasons["QUIET"] == "below_min_score"
    # Everything that cleared the floor but lost the ranking says so.
    assert reasons["S9"] == "not_top_ranked"
    # Every instrument is accounted for: kept or dropped, never vanished.
    assert len(finalists) + len(drops) == len(snaps)


def test_prescreen_is_deterministic_on_ties():
    snaps = [_snap("BBB"), _snap("AAA"), _snap("CCC")]
    first = [f.symbol for f in funnel.prescreen(snaps, 2, 0.0)[0]]
    second = [f.symbol for f in funnel.prescreen(list(reversed(snaps)), 2, 0.0)[0]]
    # Same scores, so the symbol tiebreak must make the pass reproducible.
    assert first == second == ["AAA", "BBB"]


def test_stage_a_spends_no_llm_tokens(tmp_path):
    """The free pre-screen must not touch the gate or the council."""
    cfg = _write_cfg(tmp_path, prescreen_min_score=0.99)  # drop everything
    gate, evaluator = SpyGate(), SpyEvaluator()
    snaps = [_snap(f"S{i}", change_pct=0.01, high=100.01, low=100.0)
             for i in range(50)]

    result = funnel.run_pass("equity", snapshots=snaps, gate=gate,
                             evaluator=evaluator, cfg_path=cfg)

    assert result.status == "no_finalists"
    assert gate.seen == []          # not one cheap call
    assert evaluator.seen == []     # not one council call
    assert result.council_calls == 0 and result.gate_calls == 0
    assert result.est_cost_usd == 0.0
    # All 50 were dropped for free, each with a reason.
    assert len(result.drops) == 50
    assert all(d.stage == funnel.STAGE_A for d in result.drops)


# --- Stage B: gate on finalists only ----------------------------------------

def test_gate_runs_only_on_finalists_not_the_universe(tmp_path):
    cfg = _write_cfg(tmp_path, max_finalists=4, max_survivors=5)
    gate, evaluator = SpyGate(), SpyEvaluator()
    # 30 in the universe, descending strength so the ranking is unambiguous.
    snaps = [_snap(f"S{i:02d}", change_pct=5.0 - i * 0.15) for i in range(30)]

    result = funnel.run_pass("equity", snapshots=snaps, gate=gate,
                             evaluator=evaluator, cfg_path=cfg)

    assert result.universe_count == 30
    assert len(result.finalists) == 4
    # The gate saw the 4 finalists and nothing else. This is the cost claim.
    assert len(gate.seen) == 4
    assert set(gate.seen) == {f.symbol for f in result.finalists}
    assert result.gate_calls == 4


def test_gate_rejection_is_recorded_with_its_reason(tmp_path):
    cfg = _write_cfg(tmp_path, max_finalists=3)
    gate = SpyGate(reject={"S00"})
    snaps = [_snap(f"S{i:02d}", change_pct=5.0 - i * 0.2) for i in range(3)]

    result = funnel.run_pass("equity", snapshots=snaps, gate=gate,
                             evaluator=SpyEvaluator(), cfg_path=cfg)

    assert "S00" not in result.survivors
    drop = next(d for d in result.drops if d.symbol == "S00")
    assert drop.stage == funnel.STAGE_B
    assert "too quiet" in drop.reason


def test_gate_error_fails_open_but_the_ceiling_still_binds(tmp_path):
    """A flaky gate must not suppress a real candidate, and must not blow cost."""
    cfg = _write_cfg(tmp_path, max_finalists=6, max_survivors=2)

    class BrokenGate:
        def should_review(self, state):
            raise RuntimeError("gate down")

    snaps = [_snap(f"S{i}", change_pct=5.0 - i * 0.1) for i in range(6)]
    result = funnel.run_pass("equity", snapshots=snaps, gate=BrokenGate(),
                             evaluator=SpyEvaluator(), cfg_path=cfg)

    # Fail-open let candidates through, but max_survivors still capped them.
    assert len(result.survivors) == 2
    assert result.gate_calls == 0  # no call succeeded, so none is billed


def test_survivor_ceiling_drops_the_rest(tmp_path):
    cfg = _write_cfg(tmp_path, max_finalists=8, max_survivors=3)
    snaps = [_snap(f"S{i}", change_pct=5.0 - i * 0.1) for i in range(8)]

    result = funnel.run_pass("equity", snapshots=snaps, gate=SpyGate(),
                             evaluator=SpyEvaluator(), cfg_path=cfg)

    assert len(result.survivors) == 3
    ceiling_drops = [d for d in result.drops
                     if d.reason == "survivor_ceiling_reached"]
    assert len(ceiling_drops) == 5


# --- Stage C: council on survivors only, bounded -----------------------------

def test_council_runs_only_on_survivors(tmp_path):
    cfg = _write_cfg(tmp_path, max_finalists=6, max_survivors=2)
    gate, evaluator = SpyGate(), SpyEvaluator()
    snaps = [_snap(f"S{i}", change_pct=5.0 - i * 0.1) for i in range(20)]

    result = funnel.run_pass("equity", snapshots=snaps, gate=gate,
                             evaluator=evaluator, cfg_path=cfg)

    # 20 in the universe -> 6 finalists -> 2 survivors -> 2 council calls.
    assert result.universe_count == 20
    assert len(result.finalists) == 6
    assert len(result.survivors) == 2
    assert evaluator.seen == result.survivors
    assert result.council_calls == 2
    # The council never saw anything that was not a survivor. This is the claim.
    assert set(evaluator.seen) <= set(result.survivors)
    # Both paid stages saw a small fraction of the universe.
    assert len(gate.seen) <= len(result.finalists) < result.universe_count
    assert len(evaluator.seen) <= len(gate.seen)
    # The gate stops early once max_survivors is filled: finalists arrive ranked
    # by Stage-A score, so the first N to pass ARE the best N that pass, and
    # paying to gate the rest would buy nothing.
    assert len(gate.seen) == 2


def test_per_pass_council_ceiling_binds(tmp_path):
    cfg = _write_cfg(tmp_path, max_finalists=6, max_survivors=5,
                     max_council_calls_per_pass=2,
                     discovery_daily_council_budget=99)
    evaluator = SpyEvaluator()
    snaps = [_snap(f"S{i}", change_pct=5.0 - i * 0.1) for i in range(6)]

    result = funnel.run_pass("equity", snapshots=snaps, gate=SpyGate(),
                             evaluator=evaluator, cfg_path=cfg)

    assert result.council_calls == 2
    assert len(evaluator.seen) == 2
    over = [d for d in result.drops if d.reason == "pass_council_ceiling"]
    assert len(over) == 3
    assert result.est_cost_usd == pytest.approx(2 * 0.04)


def test_daily_budget_binds_across_passes(tmp_path):
    cfg = _write_cfg(tmp_path, max_finalists=6, max_survivors=5,
                     max_council_calls_per_pass=5,
                     discovery_daily_council_budget=3)
    snaps = [_snap(f"S{i}", change_pct=5.0 - i * 0.1) for i in range(6)]

    # 1 call already spent today leaves 2 of the 3-call daily budget.
    result = funnel.run_pass("equity", snapshots=snaps, gate=SpyGate(),
                             evaluator=SpyEvaluator(), calls_used_today=1,
                             cfg_path=cfg)
    assert result.council_calls == 2
    assert result.budget_remaining == 0
    assert any(d.reason == "daily_budget_exhausted" for d in result.drops)


def test_exhausted_budget_makes_no_council_call_at_all(tmp_path):
    cfg = _write_cfg(tmp_path, discovery_daily_council_budget=4)
    evaluator = SpyEvaluator()
    snaps = [_snap(f"S{i}", change_pct=5.0 - i * 0.1) for i in range(4)]

    result = funnel.run_pass("equity", snapshots=snaps, gate=SpyGate(),
                             evaluator=evaluator, calls_used_today=4,
                             cfg_path=cfg)

    assert result.status == "budget_exhausted"
    assert result.council_calls == 0
    assert evaluator.seen == []
    assert result.est_cost_usd == 0.0
    # The cheap gate still ran: it costs fractions of a cent, and its result is
    # what tells the operator the funnel was working when the budget ran out.
    assert result.gate_calls > 0


def test_evaluator_error_drops_one_without_killing_the_pass(tmp_path):
    cfg = _write_cfg(tmp_path, max_finalists=3, max_survivors=3)

    class PartlyBroken:
        def __init__(self):
            self.seen = []

        def __call__(self, symbol):
            self.seen.append(symbol)
            if symbol == "S1":
                raise RuntimeError("provider exploded")
            return {"symbol": symbol, "verdict": "buy", "direction": "long",
                    "conviction": 0.8}

    snaps = [_snap(f"S{i}", change_pct=5.0 - i * 0.1) for i in range(3)]
    result = funnel.run_pass("equity", snapshots=snaps, gate=SpyGate(),
                             evaluator=PartlyBroken(), cfg_path=cfg)

    assert len(result.candidates) == 2
    assert any(d.reason == "evaluator_error" and d.symbol == "S1"
               for d in result.drops)


# --- narrowing invariant ----------------------------------------------------

def test_funnel_only_ever_narrows(tmp_path):
    cfg = _write_cfg(tmp_path, max_finalists=10, max_survivors=4,
                     max_council_calls_per_pass=2)
    snaps = [_snap(f"S{i:02d}", change_pct=5.0 - i * 0.08) for i in range(40)]

    r = funnel.run_pass("equity", snapshots=snaps, gate=SpyGate(),
                        evaluator=SpyEvaluator(), cfg_path=cfg)

    # The whole point of the design, in one assertion.
    assert (r.universe_count >= len(r.finalists) >= len(r.survivors)
            >= len(r.candidates))
    assert (40, 10, 4, 2) == (r.universe_count, len(r.finalists),
                              len(r.survivors), len(r.candidates))


# --- sleeve routing ---------------------------------------------------------

def test_sleeve_routing_needs_the_long_term_flag(tmp_path):
    cfg = _write_cfg(os.path.join(str(tmp_path), "a"),
                     long_term_sleeve_enabled=False)
    assert funnel.sleeve_target_for(
        {"horizon": "months", "conviction": 0.9}, cfg) == "quant_core"


def test_sleeve_routing_sends_long_horizon_conviction_to_satellite(tmp_path):
    cfg = _write_cfg(os.path.join(str(tmp_path), "b"),
                     long_term_sleeve_enabled=True)
    assert funnel.sleeve_target_for(
        {"horizon": "months", "conviction": 0.9}, cfg) == "research_satellite"
    # Below the conviction threshold stays core.
    assert funnel.sleeve_target_for(
        {"horizon": "months", "conviction": 0.5}, cfg) == "quant_core"
    # A short horizon stays core no matter how convinced the council is.
    assert funnel.sleeve_target_for(
        {"horizon": "hours", "conviction": 0.99}, cfg) == "quant_core"


# --- flags off = nothing runs -----------------------------------------------

def test_flags_off_means_no_pass_and_no_writes(tmp_path):
    cfg = _write_cfg(tmp_path, discovery_enabled=False)
    db = os.path.join(str(tmp_path), "off.db")

    out = run.run_once("crypto", db_path=db, cfg_path=cfg, now=NOW,
                       client=object(), gate=SpyGate(),
                       evaluator=SpyEvaluator(), force=True)

    assert out["status"] == "disabled"
    # Even --force cannot run a disabled funnel: the flag is the outer gate, and
    # nothing is written, not even an empty DB.
    assert not os.path.exists(db)


def test_run_due_is_disabled_when_the_flag_is_off(tmp_path):
    cfg = _write_cfg(tmp_path, discovery_enabled=False)
    out = run.run_due(db_path=os.path.join(str(tmp_path), "x.db"),
                      cfg_path=cfg, now=NOW)
    assert out["status"] == "disabled"


def test_shipped_defaults_have_discovery_off():
    """The repo's real config must ship both flags off.

    Reads the shipped config FILE, not the runtime resolution. cfg_path=None
    layers .control/controls.json over config on purpose (that is how an operator
    enables discovery at runtime), so asking None what the repo SHIPS is asking
    the wrong question: it answers with whatever the local operator last toggled.
    This test passed None and went red the first time a real operator turned
    discovery on, reporting a shipped-default regression that had not happened.
    An explicit path ignores the control file, which is the documented contract
    and the thing actually being asserted here.
    """
    shipped = "config/default_config.yaml"
    assert settings.discovery_enabled(shipped) is False
    assert settings.long_term_sleeve_enabled(shipped) is False


def test_python_defaults_match_the_cpp_struct():
    """discovery/settings.py mirrors config/config.hpp DiscoveryConfig.

    The two are separate declarations of one contract, so drift is a real risk.
    This reads the C++ header and compares the values directly.
    """
    import re
    with open("config/config.hpp", encoding="utf-8") as f:
        hpp = f.read()
    block = hpp.split("struct DiscoveryConfig {")[1].split("};")[0]

    def cpp_val(name):
        m = re.search(rf"\b{name}\s*=\s*([^;]+);", block)
        return m.group(1).strip() if m else None

    assert cpp_val("discovery_enabled") == "false"
    assert cpp_val("long_term_sleeve_enabled") == "false"
    for key in ("crypto_active_max", "max_finalists", "max_survivors",
                "max_council_calls_per_pass", "discovery_daily_council_budget",
                "crypto_interval_minutes", "equity_interval_minutes",
                "watchlist_max_size", "watchlist_stale_hours"):
        assert int(cpp_val(key)) == settings._DEFAULTS[key], key
    for key in ("discovery_est_cost_per_call_usd", "prescreen_min_score"):
        assert float(cpp_val(key)) == settings._DEFAULTS[key], key


# --- schedule ---------------------------------------------------------------

def test_crypto_is_due_hourly_around_the_clock(tmp_path):
    cfg = _write_cfg(tmp_path)
    midnight = datetime(2026, 7, 15, 3, 0, tzinfo=timezone.utc)
    # Crypto never closes, so 03:00 UTC is a fine time to run.
    ok, why = run.due("crypto", None, midnight, cfg)
    assert ok and why == "no previous pass"

    last = (midnight - timedelta(minutes=30)).strftime("%Y-%m-%dT%H:%M:%SZ")
    ok, why = run.due("crypto", last, midnight, cfg)
    assert not ok and "interval" in why

    last = (midnight - timedelta(minutes=61)).strftime("%Y-%m-%dT%H:%M:%SZ")
    assert run.due("crypto", last, midnight, cfg)[0]


def test_equity_is_never_due_outside_us_hours(tmp_path):
    cfg = _write_cfg(tmp_path)
    # 23:40 UTC is the exact hour that produced the after-hours QQQ fill the
    # market-hours entry gate was built for. Discovery must not rank equities
    # then either.
    after_hours = datetime(2026, 7, 15, 23, 40, tzinfo=timezone.utc)
    ok, why = run.due("equity", None, after_hours, cfg)
    assert not ok
    assert why == "outside US regular trading hours"

    weekend = datetime(2026, 7, 18, 15, 0, tzinfo=timezone.utc)  # Saturday
    assert run.due("equity", None, weekend, cfg)[0] is False


def test_equity_is_due_at_the_session_open(tmp_path):
    cfg = _write_cfg(tmp_path)
    at_open = datetime(2026, 7, 15, 13, 30, tzinfo=timezone.utc)
    assert run.due("equity", None, at_open, cfg)[0]


def test_us_market_open_boundaries():
    assert run.us_market_open(datetime(2026, 7, 15, 13, 30, tzinfo=timezone.utc))
    assert run.us_market_open(datetime(2026, 7, 15, 19, 59, tzinfo=timezone.utc))
    assert not run.us_market_open(datetime(2026, 7, 15, 13, 29, tzinfo=timezone.utc))
    assert not run.us_market_open(datetime(2026, 7, 15, 20, 0, tzinfo=timezone.utc))


# --- end to end through the runner ------------------------------------------

class FakeClient:
    """A Finnhub stand-in: quotes for everything, no network."""

    def __init__(self):
        self.quote_calls = 0

    def quote(self, symbol):
        self.quote_calls += 1
        return {"c": 100.0, "dp": 4.0, "h": 104.0, "l": 99.0, "o": 100.0,
                "pc": 100.0}

    def news_sentiment(self, symbol):
        return {"companyNewsScore": 0.9,
                "sentiment": {"bullishPercent": 0.9, "bearishPercent": 0.1},
                "buzz": {"buzz": 1.2, "articlesInLastWeek": 10}}


def test_run_once_persists_the_pass_and_populates_the_watchlist(tmp_path):
    cfg = _write_cfg(tmp_path, max_finalists=3, max_survivors=2,
                     max_council_calls_per_pass=2)
    db = os.path.join(str(tmp_path), "d.db")

    out = run.run_once("crypto", db_path=db, cfg_path=cfg, client=FakeClient(),
                       gate=SpyGate(), evaluator=SpyEvaluator(), now=NOW)

    assert out["status"] == "ok"
    assert out["universe_count"] == 3 and out["finalists"] == 3
    assert out["survivors"] == 2 and out["evaluated"] == 2
    assert out["council_calls"] == 2

    conn = sqlite3.connect(db)
    latest = store.latest_pass(conn, "crypto")
    assert latest["council_calls"] == 2
    assert latest["evaluated_count"] == 2
    assert len(latest["candidates"]) == 2
    # Every drop carries its stage and reason.
    assert all(d["stage"] in ("A", "B", "C") and d["reason"]
               for d in latest["drops"])

    from discovery import watchlist
    assert sorted(watchlist.active_symbols(conn)) == sorted(out["watchlist_added"])
    conn.close()


def test_second_pass_inside_the_interval_is_not_due(tmp_path):
    cfg = _write_cfg(tmp_path)
    db = os.path.join(str(tmp_path), "d.db")
    first = run.run_once("crypto", db_path=db, cfg_path=cfg, client=FakeClient(),
                         gate=SpyGate(), evaluator=SpyEvaluator(), now=NOW)
    assert first["status"] == "ok"

    ev = SpyEvaluator()
    second = run.run_once("crypto", db_path=db, cfg_path=cfg,
                          client=FakeClient(), gate=SpyGate(), evaluator=ev,
                          now=NOW + timedelta(minutes=10))
    assert second["status"] == "not_due"
    # The cadence is a cost control: a not-due pass spends nothing.
    assert ev.seen == []


def test_avoid_verdicts_do_not_reach_the_watchlist(tmp_path):
    cfg = _write_cfg(tmp_path, max_finalists=2, max_survivors=2)
    db = os.path.join(str(tmp_path), "d.db")

    def avoid_all(symbol):
        return {"symbol": symbol, "verdict": "avoid", "direction": "flat",
                "conviction": 0.2}

    out = run.run_once("crypto", db_path=db, cfg_path=cfg, client=FakeClient(),
                       gate=SpyGate(), evaluator=avoid_all, now=NOW)

    # The funnel looked and declined: the pass records it, the watchlist does
    # not collect it. A watchlist is a candidate list, not an archive of
    # rejections.
    assert out["watchlist_added"] == []
    conn = sqlite3.connect(db)
    assert store.latest_pass(conn, "crypto")["evaluated_count"] == 2
    from discovery import watchlist
    assert watchlist.active_symbols(conn) == []
    conn.close()


def test_no_finnhub_key_reports_unavailable_not_a_crash(tmp_path, monkeypatch):
    cfg = _write_cfg(tmp_path)
    monkeypatch.delenv("FINNHUB_API_KEY", raising=False)
    from discovery import finnhub_source
    monkeypatch.setattr(finnhub_source, "credentials", None)

    out = run.run_once("crypto", db_path=os.path.join(str(tmp_path), "d.db"),
                       cfg_path=cfg, now=NOW)
    assert out["status"] == "unavailable"
    assert "FINNHUB_API_KEY" in out["reason"]


# --- The engine trigger path: due_status, onboarding, and the bridge ---------
#
# THE DEFECT these cover: discovery_enabled was true in controls.json, the engine
# restarted, and no pass ever ran. The funnel below was correct the whole time.
# Nothing CALLED it: run_due's only non-test caller was ops/maintenance's CLI,
# and no cron, watchdog, supervisor, or start script ever ran that CLI. So the
# engine now drives the funnel over the bridge, and these pin that path.

def test_due_status_is_the_one_cadence_authority_the_engine_asks(tmp_path):
    """The engine does not decide the cadence, it asks. This is what it asks.

    Written twice (once in Python, once in C++) the hourly interval and the
    equities US-hours rule would drift, and a drifted cadence is invisible: the
    layer just quietly runs at the wrong time. So there is one authority.
    """
    cfg = _write_cfg(tmp_path)
    db = os.path.join(str(tmp_path), "due.db")

    # No pass on record: due, and says so rather than returning a bare bool.
    out = run.due_status("crypto", db_path=db, cfg_path=cfg, now=NOW)
    assert out["enabled"] is True
    assert out["due"] is True
    assert out["reason"] == "no previous pass"

    # Crypto is due hourly around the clock, including at 3am on a Sunday: it
    # never closes. This is the case the engine most needs right, because it is
    # the one testable outside US hours.
    sunday_3am = datetime(2026, 7, 19, 3, 0, tzinfo=timezone.utc)
    assert run.due_status("crypto", db_path=db, cfg_path=cfg,
                          now=sunday_3am)["due"] is True

    # Equities are NOT due at 3am on a Sunday, and the reason names the rule.
    eq = run.due_status("equity", db_path=db, cfg_path=cfg, now=sunday_3am)
    assert eq["due"] is False
    assert "outside US regular trading hours" in eq["reason"]


def test_due_status_reports_the_flag_off_so_the_engine_can_see_a_mismatch(tmp_path):
    """Engine on, Python off is a real state, and it must be visible.

    Both sides read discovery_enabled from the same controls.json, so they should
    agree. When they do not, the engine logs it loudly rather than starting a
    pass the funnel will silently refuse. That silent refusal is exactly the
    class of failure being fixed.
    """
    cfg = _write_cfg(tmp_path, discovery_enabled=False)
    out = run.due_status("crypto", db_path=os.path.join(str(tmp_path), "x.db"),
                         cfg_path=cfg, now=NOW)
    assert out["enabled"] is False
    assert out["due"] is False
    assert "discovery_enabled is false" in out["reason"]


def test_due_status_respects_the_interval_and_says_how_long_is_left(tmp_path):
    cfg = _write_cfg(tmp_path, crypto_interval_minutes=60)
    db = os.path.join(str(tmp_path), "int.db")
    conn = sqlite3.connect(db)
    store.ensure_schema(conn)
    store.record_pass(conn, {"asset_class": "crypto", "status": "ok",
                             "ts": NOW.strftime("%Y-%m-%dT%H:%M:%SZ"),
                             "universe_count": 3, "finalists_count": 1,
                             "survivors_count": 1, "evaluated_count": 1,
                             "council_calls": 1, "est_cost_usd": 0.04,
                             "candidates": [], "drops": []})
    conn.commit()
    conn.close()

    # 30 minutes after a pass: not due, and the reason carries the arithmetic so
    # an operator reading the events log can see WHY, not just that.
    out = run.due_status("crypto", db_path=db, cfg_path=cfg,
                         now=NOW + timedelta(minutes=30))
    assert out["due"] is False
    assert "interval 60m" in out["reason"]

    # 61 minutes after: due again.
    assert run.due_status("crypto", db_path=db, cfg_path=cfg,
                          now=NOW + timedelta(minutes=61))["due"] is True


def test_onboard_backfills_bars_for_a_surfaced_symbol(tmp_path, monkeypatch):
    """A surfaced symbol with no bars can never warm, so it could never trade.

    Without this the funnel only NAMES a candidate: the engine's warm gate holds
    a bar-less symbol back forever, correctly, and the operator sees a discovery
    layer that finds names and never acts on them.
    """
    calls = {}

    def fake_backfill(db_path, symbols):
        calls["symbols"] = list(symbols)
        return {"status": "ok", "written": {f"{s}:5min": 1440 for s in symbols}}

    import market_data.alpaca_source as src
    monkeypatch.setattr(src, "backfill", fake_backfill)

    out = run.onboard(["AVAX/USD", "LINK/USD"], db_path="x.db")
    assert out["status"] == "ok"
    # The SAME backfill the whitelist uses at startup, called with the new
    # symbols, so a discovered symbol warms through the normal path.
    assert calls["symbols"] == ["AVAX/USD", "LINK/USD"]
    assert out["onboarded"] == ["AVAX/USD", "LINK/USD"]


def test_onboard_does_not_call_a_symbol_ready_when_no_bars_landed(tmp_path,
                                                                  monkeypatch):
    """Zero bars is reported as zero bars, never as onboarded.

    A symbol Alpaca has no history for (a coin it does not carry) must not be
    reported ready. It stays cold, the engine says COLD, and it never trades on
    nothing.
    """
    import market_data.alpaca_source as src
    monkeypatch.setattr(src, "backfill", lambda db, symbols: {
        "status": "ok", "written": {"AVAX/USD:5min": 1440, "FAKE/USD:5min": 0}})

    out = run.onboard(["AVAX/USD", "FAKE/USD"], db_path="x.db")
    assert out["onboarded"] == ["AVAX/USD"]
    assert out["no_bars"] == ["FAKE/USD"]


def test_onboard_degrades_cleanly_without_data_credentials(monkeypatch):
    """No key means no bars, reported, never a crash and never a fake success."""
    import market_data.alpaca_source as src
    monkeypatch.setattr(src, "backfill", lambda db, symbols: {
        "status": "unavailable", "reason": "no data credentials"})

    out = run.onboard(["AVAX/USD"], db_path="x.db")
    assert out["status"] == "unavailable"
    assert out["onboarded"] == []


def test_onboard_never_raises_into_the_pass(monkeypatch):
    """Discovery is advisory. A backfill fault must not take the loop down."""
    import market_data.alpaca_source as src

    def boom(db, symbols):
        raise RuntimeError("alpaca exploded")

    monkeypatch.setattr(src, "backfill", boom)
    out = run.onboard(["AVAX/USD"], db_path="x.db")
    assert out["status"] == "error"
    assert out["reason"] == "RuntimeError"
    # The message is the TYPE only. A backfill exception can carry a URL, and an
    # Alpaca URL is not a secret today, but the reason is rendered in the GUI, so
    # the type name is what travels.
    assert "alpaca exploded" not in str(out)


def test_a_pass_onboards_what_it_surfaces(tmp_path, monkeypatch):
    """End to end: a surfaced candidate leaves the pass with its bars pulled.

    This is the handoff. The pass writes bars, the engine reads the watchlist and
    seeds its history from that table, and neither calls the other.
    """
    cfg = _write_cfg(tmp_path)
    db = os.path.join(str(tmp_path), "onb.db")
    got = {}

    import market_data.alpaca_source as src
    def fake_backfill(db_path, symbols):
        # Writes REAL rows like the real backfill: serviceability verification
        # (2026-07-20) checks the bars table, not the return value alone.
        got["symbols"] = list(symbols)
        conn = sqlite3.connect(db_path)
        try:
            src.ensure_bars_schema(conn)
            for s in symbols:
                conn.execute(
                    "INSERT INTO bars(venue,symbol,timeframe,timestamp,open,"
                    "high,low,close,volume,source) VALUES('alpaca',?,?,"
                    "'2026-07-01T00:00:00Z',1,2,0.5,1.5,10,'backfill')",
                    (s, "5min"))
            conn.commit()
        finally:
            conn.close()
        return {"status": "ok", "written": {f"{s}:5min": 1440 for s in symbols}}
    monkeypatch.setattr(src, "backfill", fake_backfill)

    # Stub the Finnhub-backed snapshot build: this test is about the handoff
    # AFTER the funnel picks a candidate, not about the pre-screen.
    snaps = [_snap("SOL/USD", change_pct=0.08, high=105.0, low=100.0)]
    monkeypatch.setattr(funnel, "build_snapshots",
                        lambda symbols, client, whale=None: snaps)

    out = run.run_once("crypto", db_path=db, cfg_path=cfg, now=NOW,
                       client=object(), gate=SpyGate(),
                       evaluator=SpyEvaluator(), force=True)

    assert out["status"] == "ok"
    # The pass surfaced a candidate, and that candidate left the pass with bars
    # already pulled. No symbol is left named-but-barless.
    assert out["watchlist_added"] == ["SOL/USD"]
    assert got["symbols"] == ["SOL/USD"]
    assert out["onboard_status"] == "ok"
    assert out["onboarded"] == ["SOL/USD"]
    assert out["onboard_refused"] == []


def test_a_pass_refuses_a_candidate_whose_backfill_returns_nothing(
        tmp_path, monkeypatch):
    """Serviceability verification (2026-07-20): the MANA/USD, RUNE/USD hole.

    Discovery ranks through Finnhub while onboarding backfills through Alpaca,
    and the venues do not carry the same pairs. A candidate whose backfill ran
    and returned NOTHING is not added to the watchlist: it could only ever sit
    symbol_unavailable. The refusal is journalled (applied=0) with the reason.
    """
    cfg = _write_cfg(tmp_path)
    db = os.path.join(str(tmp_path), "refuse.db")

    import market_data.alpaca_source as src
    def fake_backfill(db_path, symbols):
        # The backfill RAN (status ok) and the venue served zero bars.
        conn = sqlite3.connect(db_path)
        try:
            src.ensure_bars_schema(conn)
            conn.commit()
        finally:
            conn.close()
        return {"status": "ok", "written": {f"{s}:5min": 0 for s in symbols}}
    monkeypatch.setattr(src, "backfill", fake_backfill)

    snaps = [_snap("MANA/USD", change_pct=0.08, high=105.0, low=100.0)]
    monkeypatch.setattr(funnel, "build_snapshots",
                        lambda symbols, client, whale=None: snaps)

    out = run.run_once("crypto", db_path=db, cfg_path=cfg, now=NOW,
                       client=object(), gate=SpyGate(),
                       evaluator=SpyEvaluator(), force=True)

    assert out["status"] == "ok"
    assert out["watchlist_added"] == []
    assert out["onboard_refused"] == ["MANA/USD"]
    conn = sqlite3.connect(db)
    try:
        from discovery import watchlist as wl
        assert wl.active_symbols(conn) == []
        events = wl.recent_events(conn, limit=10)
        refusal = [e for e in events if e["symbol"] == "MANA/USD"
                   and not e["applied"]]
        assert refusal, events
        assert "backfill returned no bars" in refusal[0]["reason"]
    finally:
        conn.close()


# --- The payload bugs: the stages must hand the models real market data -------
#
# Both stages built a dict whose KEYS did not match what the prompt reads, so the
# models were asked to judge an instrument with no price and no return. They
# correctly said no, every time, in every market. Nobody saw it because the
# funnel had never actually run. These pin the key contract on both sides.

def test_stage_b_hands_the_gate_a_market_snapshot_not_score_components():
    """THE STAGE-B BUG: the gate got the pre-screen's score components.

    build_user_prompt reads symbol/venue/price/ret_5/imbalance/catalyst/
    volatility. The components dict shares exactly ONE key name with that list
    (volatility) and no others, so every finalist arrived as a zero-price,
    zero-return instrument and the gate rejected 12 of 12 on every pass.
    """
    f = funnel.Finalist("ETH/USD", 0.48,
                        {"momentum": 0.9, "volatility": 0.5, "gap": 0.1},
                        False, "",
                        {"price": 1826.39, "change_pct": -5.12, "high": 1929.0,
                         "low": 1821.0, "open": 1925.0, "prev_close": 1924.0})
    st = funnel.gate_state(f)

    # The real market reaches the gate.
    assert st["price"] == 1826.39
    assert st["ret_5"] == pytest.approx(-0.0512)   # a FRACTION, not a percent
    assert st["volatility"] > 0.0

    # And the score components do NOT leak in wearing the prompt's key names.
    # `momentum` 0.9 is a rank component, not a market signal.
    assert "momentum" not in st

    # The prompt the model actually sees carries the price.
    from llm_consensus.providers import build_user_prompt
    prompt = build_user_prompt(st)
    assert "1826.39" in prompt
    assert '"price": 0' not in prompt


def test_stage_c_hands_the_council_the_market_not_just_a_price():
    """THE STAGE-C BUG: the council state carried symbol + price and nothing else.

    Everything build_user_prompt reads besides price defaulted to 0.0, so the
    council judged a priced instrument with zero return and zero volatility and
    returned avoid at conviction 0.0 for every survivor, at a real council call
    each.
    """
    from discovery.evaluate import market_state_from
    st = market_state_from({"price": 100.0, "change_pct": 14.0, "high": 104.0,
                            "low": 90.0, "open": 91.0, "prev_close": 88.0})
    assert st["price"] == 100.0
    assert st["ret_5"] == pytest.approx(0.14)
    assert st["volatility"] == pytest.approx(0.14)


def test_an_absent_signal_stays_absent_rather_than_becoming_zero():
    """Missing is not zero, and that distinction is the whole bug.

    Crypto has no news sentiment on the free tier. Reporting catalyst=0.0 tells
    the model "measured, and there is no catalyst", which is a lie about a field
    that was never fetched. The key is omitted instead.
    """
    from discovery.evaluate import market_state_from
    crypto = market_state_from({"price": 100.0, "change_pct": 5.0,
                                "high": 102.0, "low": 98.0})
    assert "catalyst" not in crypto

    equity = market_state_from({"price": 100.0, "change_pct": 5.0, "high": 102.0,
                                "low": 98.0, "sentiment_score": 0.82})
    assert equity["catalyst"] == pytest.approx(0.82)


def test_the_discovery_gate_prompt_never_invents_absent_fields():
    """The discovery gate shows only what discovery has.

    The council's gate renders order_book_imbalance and catalyst_score as 0.0
    when absent. Those two zeros are what made it call a +14% move "flat".
    """
    from discovery.gate import build_discovery_prompt
    f = funnel.Finalist("BTC/USD", 0.9, {}, False, "",
                        {"price": 100.0, "change_pct": 14.0, "high": 104.0,
                         "low": 90.0})
    prompt = build_discovery_prompt(funnel.gate_state(f))
    assert "order_book_imbalance" not in prompt
    assert "news_sentiment" not in prompt      # crypto: absent, so not shown
    assert "0.14" in prompt                    # the move IS shown


def test_the_finnhub_crypto_symbol_mapping():
    """Finnhub does not serve Alpaca's crypto symbols, and does not say so.

    /quote?symbol=BTC/USD returns HTTP 200 with an all-zero body, so every crypto
    name silently dropped out of the pre-screen and each pass reported no_data.
    """
    from discovery.finnhub_source import finnhub_symbol
    assert finnhub_symbol("BTC/USD") == "BINANCE:BTCUSDT"
    assert finnhub_symbol("ETH/USD") == "BINANCE:ETHUSDT"
    # Equities are already Finnhub ids and must pass through untouched.
    assert finnhub_symbol("AAPL") == "AAPL"
    assert finnhub_symbol("SPY") == "SPY"


def test_the_all_zero_quote_finnhub_returns_for_an_unmapped_symbol_is_no_data():
    """The zero body must read as absent, never as a real price of 0."""
    from discovery.finnhub_source import parse_quote
    zeros = {"c": 0, "d": None, "dp": None, "h": 0, "l": 0, "o": 0, "pc": 0,
             "t": 0}
    assert parse_quote(zeros) == {}


def test_stage_c_does_not_re_gate_what_stage_b_already_gated(monkeypatch):
    """Each stage screens ONCE. Stage C re-gating was a wall, not a saving.

    consensus() runs the trading base-check gate by default, and that gate
    skipped every discovery survivor on the absent order book. So consensus
    returned a flat verdict WITHOUT calling a provider: Stage C recorded council
    calls that never happened and avoid verdicts nobody had reasoned about.
    """
    from discovery import evaluate
    seen = {}

    def fake_consensus(state, providers=None, cfg_path=None, gate=None):
        seen["gate"] = gate
        seen["state"] = state
        class R:
            bias, confidence, edge, agreement_count, per_model = 0.5, 0.8, 0.1, 3, []
        return R()

    import llm_consensus
    monkeypatch.setattr(llm_consensus, "consensus", fake_consensus)
    ev = evaluate.four_level_evaluator(
        price_for=lambda s: 100.0,
        snapshot_for=lambda s: {"price": 100.0, "change_pct": 9.0,
                                "high": 105.0, "low": 96.0},
        category_for=lambda s: "crypto")
    ev("BTC/USD")

    # An explicit gate is passed, so consensus cannot fall back to the trading
    # gate that structurally rejects discovery candidates.
    assert seen["gate"] is not None
    assert seen["gate"].should_review({}).proceed is True
    # And the council sees the movement, not just a price.
    assert seen["state"]["ret_5"] == pytest.approx(0.09)
