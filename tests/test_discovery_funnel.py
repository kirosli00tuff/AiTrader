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
    """The repo's real config must ship both flags off."""
    assert settings.discovery_enabled(None) is False
    assert settings.long_term_sleeve_enabled(None) is False


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
