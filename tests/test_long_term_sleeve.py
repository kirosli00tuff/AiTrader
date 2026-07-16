"""Tests for the research_satellite long-term strategy and the Stage-C fusion.

The claims that matter:
  * quality AND catalyst must both hold. Either alone is not a trade.
  * a thesis may only TIGHTEN the stop, never widen it. A conviction cannot buy
    itself more room to be wrong.
  * the advisory layers (DNN, whale) can never flip a verdict on their own.
  * with long_term_sleeve_enabled off, research_thesis is the original path.
  * no key value reaches a thesis.

Mocked Finnhub and mocked council throughout. No network.
"""
from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone

import pytest
import yaml

from discovery import evaluate
from discovery.finnhub_source import parse_basic_financials
from research_satellite import long_term

NOW = datetime(2026, 7, 15, 15, 0, tzinfo=timezone.utc)


# --- fakes ------------------------------------------------------------------

class FakeCouncil:
    def __init__(self, bias=0.6, confidence=0.8, edge=0.05, agreement=3,
                 verdict="buy"):
        self.bias, self.confidence, self.edge = bias, confidence, edge
        self.agreement_count, self.verdict = agreement, verdict
        self.per_model = []


class FakeClient:
    """A Finnhub stand-in driven by injected payloads."""

    def __init__(self, *, financials=None, sentiment=None, recs=None,
                 earnings=None, price=200.0):
        self._fin = financials
        self._sent = sentiment
        self._recs = recs
        self._earn = earnings
        self._price = price

    def basic_financials(self, symbol, metric="all"):
        return self._fin

    def news_sentiment(self, symbol):
        return self._sent

    def recommendation_trends(self, symbol):
        return self._recs

    def earnings_calendar(self, frm, to, symbol=None):
        return self._earn

    def quote(self, symbol):
        return {"c": self._price, "dp": 1.0, "h": self._price * 1.01,
                "l": self._price * 0.99, "o": self._price, "pc": self._price}


_GOOD_FIN = {"metric": {"roeTTM": 25.0, "netProfitMarginTTM": 20.0,
                        "revenueGrowthTTMYoy": 12.0,
                        "peBasicExclExtraTTM": 22.0,
                        "52WeekHigh": 260.0, "52WeekLow": 150.0}}
_POOR_FIN = {"metric": {"roeTTM": -9.0, "netProfitMarginTTM": -14.0,
                        "revenueGrowthTTMYoy": -18.0,
                        "peBasicExclExtraTTM": 0,
                        "52WeekHigh": 12.0, "52WeekLow": 3.0}}
_EARNINGS_SOON = {"earningsCalendar": [
    {"symbol": "AAPL", "date": (NOW + timedelta(days=7)).strftime("%Y-%m-%d"),
     "epsEstimate": 1.6}]}


def _cfg(tmp_path, *, long_term_on=True) -> str:
    os.makedirs(str(tmp_path), exist_ok=True)
    p = os.path.join(str(tmp_path), f"lt-{int(long_term_on)}.yaml")
    with open(p, "w", encoding="utf-8") as f:
        yaml.safe_dump({
            "discovery": {"discovery_enabled": True,
                          "long_term_sleeve_enabled": long_term_on},
            "sleeves": {"research_conviction_threshold": 0.70},
            "council": {"council_min_confidence": 0.6},
        }, f)
    return p


# --- quality screen ---------------------------------------------------------

def test_quality_score_rewards_a_good_business():
    good, _ = long_term.quality_score(parse_basic_financials(_GOOD_FIN))
    poor, _ = long_term.quality_score(parse_basic_financials(_POOR_FIN))
    assert good > poor
    assert good >= long_term.QUALITY_MIN_SCORE
    assert poor < long_term.QUALITY_MIN_SCORE


def test_quality_score_treats_missing_data_as_neutral_not_bad():
    """Thin coverage must not masquerade as poor quality."""
    partial, breakdown = long_term.quality_score({"roe_ttm": None,
                                                  "net_margin_ttm": None,
                                                  "revenue_growth_yoy": None,
                                                  "pe_ttm": None})
    assert breakdown["roe"] == 0.5
    assert partial == pytest.approx(0.5)


def test_quality_score_with_no_fundamentals_is_zero():
    assert long_term.quality_score({})[0] == 0.0


# --- catalyst ---------------------------------------------------------------

def test_earnings_inside_the_window_is_a_catalyst():
    c = long_term.find_catalyst(
        earnings=[{"symbol": "AAPL",
                   "date": (NOW + timedelta(days=7)).strftime("%Y-%m-%d")}],
        sentiment=None, recommendations=None, symbol="AAPL", now=NOW)
    assert c["found"] and c["kind"] == "earnings"


def test_earnings_beyond_the_window_is_not_a_catalyst():
    c = long_term.find_catalyst(
        earnings=[{"symbol": "AAPL",
                   "date": (NOW + timedelta(days=90)).strftime("%Y-%m-%d")}],
        sentiment=None, recommendations=None, symbol="AAPL", now=NOW)
    assert not c["found"]


def test_earnings_for_another_symbol_is_not_a_catalyst():
    c = long_term.find_catalyst(
        earnings=[{"symbol": "MSFT",
                   "date": (NOW + timedelta(days=3)).strftime("%Y-%m-%d")}],
        sentiment=None, recommendations=None, symbol="AAPL", now=NOW)
    assert not c["found"]


def test_a_strong_sentiment_shift_is_a_catalyst_in_either_direction():
    bull = long_term.find_catalyst(earnings=None, sentiment={"score": 0.85},
                                   recommendations=None, symbol="A", now=NOW)
    bear = long_term.find_catalyst(earnings=None, sentiment={"score": 0.15},
                                   recommendations=None, symbol="A", now=NOW)
    assert bull["kind"] == bear["kind"] == "sentiment_shift"
    assert "bullish" in bull["detail"] and "bearish" in bear["detail"]


def test_a_mild_sentiment_shift_is_not_a_catalyst():
    c = long_term.find_catalyst(earnings=None, sentiment={"score": 0.55},
                                recommendations=None, symbol="A", now=NOW)
    assert not c["found"]


def test_an_analyst_upgrade_is_a_catalyst():
    c = long_term.find_catalyst(earnings=None, sentiment=None,
                                recommendations={"score": 0.6,
                                                 "period": "2026-07-01"},
                                symbol="A", now=NOW)
    assert c["found"] and c["kind"] == "analyst_upgrade"


def test_earnings_outranks_a_soft_signal():
    """A dated event beats a soft one when both are present."""
    c = long_term.find_catalyst(
        earnings=[{"symbol": "A",
                   "date": (NOW + timedelta(days=2)).strftime("%Y-%m-%d")}],
        sentiment={"score": 0.9}, recommendations={"score": 0.9},
        symbol="A", now=NOW)
    assert c["kind"] == "earnings"


def test_no_signals_means_no_catalyst():
    c = long_term.find_catalyst(earnings=None, sentiment=None,
                                recommendations=None, symbol="A", now=NOW)
    assert not c["found"] and c["detail"] == "no catalyst"


# --- the screen needs BOTH --------------------------------------------------

def test_quality_without_a_catalyst_is_not_a_trade():
    client = FakeClient(financials=_GOOD_FIN,
                        sentiment={"companyNewsScore": 0.5}, recs=[],
                        earnings={"earningsCalendar": []})
    out = long_term.screen("AAPL", client, NOW)
    assert out["passes"] is False
    assert out["reason"] == "no catalyst"


def test_catalyst_without_quality_is_a_gamble_not_a_trade():
    client = FakeClient(financials=_POOR_FIN,
                        sentiment={"companyNewsScore": 0.9}, recs=[],
                        earnings=_EARNINGS_SOON)
    out = long_term.screen("AAPL", client, NOW)
    assert out["passes"] is False
    assert "quality" in out["reason"]


def test_quality_plus_catalyst_passes():
    client = FakeClient(financials=_GOOD_FIN,
                        sentiment={"companyNewsScore": 0.5}, recs=[],
                        earnings=_EARNINGS_SOON)
    out = long_term.screen("AAPL", client, NOW)
    assert out["passes"] is True
    assert out["catalyst"]["kind"] == "earnings"


# --- target and invalidation ------------------------------------------------

def test_target_and_invalidation_are_derived_from_the_52w_range():
    fin = {"week52_high": 260.0, "week52_low": 150.0}
    lo = long_term.derive_target_and_invalidation(
        direction="long", price=200.0, conviction=0.5, fin=fin)
    hi = long_term.derive_target_and_invalidation(
        direction="long", price=200.0, conviction=1.0, fin=fin)

    # Higher conviction reaches further toward the 52w high, never past it.
    assert 200.0 < lo["target"] < hi["target"] <= 260.0
    # Invalidation sits below entry, above the 52w low.
    assert 150.0 < lo["invalidation_price"] < 200.0
    assert "thesis broken" in lo["invalidation"]


def test_target_falls_back_when_the_range_is_unknown():
    out = long_term.derive_target_and_invalidation(
        direction="long", price=100.0, conviction=0.5, fin={})
    assert out["target"] > 100.0
    assert 0 < out["invalidation_price"] < 100.0


def test_no_price_yields_no_levels():
    out = long_term.derive_target_and_invalidation(
        direction="long", price=0.0, conviction=0.9, fin={})
    assert out["target"] == 0.0 and out["invalidation_price"] == 0.0


# --- the tighten-only stop rule (safety) ------------------------------------

def test_invalidation_may_tighten_the_stop():
    # ATR stop at 90, invalidation at 95: the tighter (95) wins.
    stop = long_term.invalidation_stop(direction="long", entry_price=100.0,
                                       atr_stop=90.0, invalidation_price=95.0)
    assert stop == 95.0


def test_invalidation_may_never_widen_the_stop():
    """A thesis cannot buy itself more room to be wrong."""
    # ATR stop at 95, invalidation at 80: the ATR stop (tighter) still wins.
    stop = long_term.invalidation_stop(direction="long", entry_price=100.0,
                                       atr_stop=95.0, invalidation_price=80.0)
    assert stop == 95.0


def test_invalidation_stop_for_a_short_takes_the_lower_level():
    # Short: both stops sit above entry, so the tighter (lower) wins.
    assert long_term.invalidation_stop(direction="short", entry_price=100.0,
                                       atr_stop=110.0,
                                       invalidation_price=105.0) == 105.0
    assert long_term.invalidation_stop(direction="short", entry_price=100.0,
                                       atr_stop=105.0,
                                       invalidation_price=120.0) == 105.0


def test_missing_levels_fall_back_to_the_atr_stop():
    assert long_term.invalidation_stop(direction="long", entry_price=100.0,
                                       atr_stop=90.0,
                                       invalidation_price=0.0) == 90.0
    assert long_term.invalidation_stop(direction="long", entry_price=0.0,
                                       atr_stop=90.0,
                                       invalidation_price=95.0) == 90.0


# --- Stage-C fusion: advisory stays advisory --------------------------------

def test_advisory_layers_cannot_flip_a_verdict():
    """DNN and whale can temper conviction, never reverse the council."""
    council = FakeCouncil(bias=0.6, confidence=0.8)
    # Both advisory layers maximally disagree.
    v = evaluate.build_verdict(symbol="A", council=council,
                               dnn={"bias": -1.0}, whale={"whale_bias": -1.0},
                               conviction_floor=0.6)
    assert v["direction"] == "long"          # direction still the council's
    # Conviction was cut, but only by the bounded budget.
    assert v["conviction"] == pytest.approx(0.8 - evaluate._ADVISORY_ADJUST_MAX)


def test_advisory_agreement_lifts_conviction_within_the_bound():
    council = FakeCouncil(bias=0.6, confidence=0.8)
    v = evaluate.build_verdict(symbol="A", council=council,
                               dnn={"bias": 1.0}, whale={"whale_bias": 1.0},
                               conviction_floor=0.6)
    assert v["conviction"] == pytest.approx(0.8 + evaluate._ADVISORY_ADJUST_MAX)


def test_advisory_adjustment_is_bounded_both_ways():
    for dnn in (-1.0, -0.5, 0.0, 0.5, 1.0):
        for whale in (-1.0, -0.5, 0.0, 0.5, 1.0):
            adj = evaluate.advisory_adjustment(0.5, dnn, whale)
            assert abs(adj) <= evaluate._ADVISORY_ADJUST_MAX + 1e-9


def test_a_flat_council_means_no_advisory_adjustment():
    # No direction to agree with, so the advisory layers have nothing to say.
    assert evaluate.advisory_adjustment(0.0, 1.0, 1.0) == 0.0


def test_a_flat_council_yields_avoid():
    v = evaluate.build_verdict(
        symbol="A", council=FakeCouncil(bias=0.0, confidence=0.9),
        dnn={}, whale={}, conviction_floor=0.6)
    assert v["verdict"] == "avoid"
    assert v["size_pct"] == 0.0


def test_conviction_below_the_floor_yields_avoid():
    v = evaluate.build_verdict(
        symbol="A", council=FakeCouncil(bias=0.6, confidence=0.4),
        dnn={}, whale={}, conviction_floor=0.6)
    assert v["verdict"] == "avoid"
    assert v["size_pct"] == 0.0


def test_a_short_bias_yields_sell():
    v = evaluate.build_verdict(
        symbol="A", council=FakeCouncil(bias=-0.6, confidence=0.9),
        dnn={}, whale={}, conviction_floor=0.6)
    assert v["verdict"] == "sell" and v["direction"] == "short"


def test_suggested_size_is_advisory_and_bounded():
    v = evaluate.build_verdict(
        symbol="A", council=FakeCouncil(bias=0.9, confidence=1.0),
        dnn={}, whale={}, conviction_floor=0.6)
    # Suggested sizing never approaches a full allocation: the engine's hard cap
    # and the RiskGate rule, and both can only reduce this.
    assert 0.0 < v["size_pct"] <= 0.5


# --- long_term_thesis end to end --------------------------------------------

def test_long_term_thesis_produces_a_full_structured_thesis(tmp_path,
                                                            monkeypatch):
    cfg = _cfg(tmp_path)
    monkeypatch.setattr(evaluate, "four_level_evaluator",
                        lambda **kw: (lambda s: {
                            "symbol": s, "verdict": "buy", "direction": "long",
                            "conviction": 0.85, "agreement": 3,
                            "rationale": "council likes it"}))
    client = FakeClient(financials=_GOOD_FIN,
                        sentiment={"companyNewsScore": 0.5}, recs=[],
                        earnings=_EARNINGS_SOON, price=200.0)

    t = long_term.long_term_thesis({"symbol": "AAPL", "category": "equity"},
                                   client=client, cfg_path=cfg, now=NOW)

    assert t["direction"] == "long"
    assert t["conviction"] == 0.85
    assert t["horizon"] == "months"      # a hold, not a scalp
    assert t["target"] > 200.0
    assert 0 < t["invalidation_price"] < 200.0
    assert "thesis broken" in t["invalidation"]
    assert t["catalyst"] == "earnings"
    assert t["quality"] > 0
    assert t["mode"] == "long_term_hold"


def test_a_screened_out_candidate_never_reaches_the_council(tmp_path,
                                                            monkeypatch):
    """The strategy is quality-and-catalyst PLUS council, never council alone."""
    cfg = _cfg(tmp_path)
    called = []
    monkeypatch.setattr(evaluate, "four_level_evaluator",
                        lambda **kw: (lambda s: called.append(s) or {}))
    client = FakeClient(financials=_POOR_FIN,
                        sentiment={"companyNewsScore": 0.5}, recs=[],
                        earnings={"earningsCalendar": []})

    t = long_term.long_term_thesis({"symbol": "WEAK"}, client=client,
                                   cfg_path=cfg, now=NOW)

    assert t["conviction"] == 0.0 and t["direction"] == "flat"
    assert "screened out" in t["rationale"]
    assert called == []   # not one council token spent on a screened-out name


def test_a_flat_council_yields_a_zero_conviction_thesis(tmp_path, monkeypatch):
    cfg = _cfg(tmp_path)
    monkeypatch.setattr(evaluate, "four_level_evaluator",
                        lambda **kw: (lambda s: {"symbol": s,
                                                 "direction": "flat",
                                                 "conviction": 0.9,
                                                 "rationale": "no view"}))
    client = FakeClient(financials=_GOOD_FIN,
                        sentiment={"companyNewsScore": 0.5}, recs=[],
                        earnings=_EARNINGS_SOON)
    t = long_term.long_term_thesis({"symbol": "AAPL"}, client=client,
                                   cfg_path=cfg, now=NOW)
    # The engine will not act on this: conviction 0 is below any threshold.
    assert t["conviction"] == 0.0
    assert t["direction"] == "flat"


def test_a_broken_council_degrades_to_flat_never_raises(tmp_path, monkeypatch):
    cfg = _cfg(tmp_path)

    def _boom(**kw):
        def _f(_s):
            raise RuntimeError("council down")
        return _f

    monkeypatch.setattr(evaluate, "four_level_evaluator", _boom)
    client = FakeClient(financials=_GOOD_FIN,
                        sentiment={"companyNewsScore": 0.5}, recs=[],
                        earnings=_EARNINGS_SOON)
    t = long_term.long_term_thesis({"symbol": "AAPL"}, client=client,
                                   cfg_path=cfg, now=NOW)
    assert t["conviction"] == 0.0
    assert t["rationale"] == "council unavailable"


def test_no_finnhub_key_means_no_long_term_thesis(tmp_path, monkeypatch):
    cfg = _cfg(tmp_path)
    monkeypatch.delenv("FINNHUB_API_KEY", raising=False)
    from discovery import finnhub_source
    monkeypatch.setattr(finnhub_source, "credentials", None)

    t = long_term.long_term_thesis({"symbol": "AAPL"}, cfg_path=cfg, now=NOW)
    assert t["conviction"] == 0.0
    assert "FINNHUB_API_KEY" in t["rationale"]


# --- the flag gate ----------------------------------------------------------

def test_flag_off_keeps_the_original_research_path(tmp_path, monkeypatch):
    """With long_term_sleeve_enabled off, research_thesis is unchanged."""
    cfg = _cfg(tmp_path, long_term_on=False)
    called = []
    import research_satellite.research as research_mod
    monkeypatch.setattr(research_mod, "consensus",
                        lambda *a, **k: called.append(1) or FakeCouncil())

    t = research_mod.research_thesis({"symbol": "BTC/USD"}, cfg_path=cfg)

    # The original council-mapped shape: no target, no invalidation.
    assert "target" not in t
    assert "invalidation" not in t
    assert called == [1]          # it went through the original consensus path
    assert t["horizon"] in ("weeks", "months")


def test_flag_on_routes_to_the_long_term_strategy(tmp_path, monkeypatch):
    cfg = _cfg(tmp_path, long_term_on=True)
    import research_satellite.research as research_mod
    monkeypatch.setattr("research_satellite.long_term.long_term_thesis",
                        lambda payload, providers=None, cfg_path=None: {
                            "symbol": payload["symbol"], "direction": "long",
                            "conviction": 0.9, "target": 250.0,
                            "invalidation": "close below 180"})

    t = research_mod.research_thesis({"symbol": "AAPL"}, cfg_path=cfg)
    assert t["target"] == 250.0
    assert t["invalidation"] == "close below 180"
    # The engine's conviction gate is echoed for the GUI either way.
    assert t["conviction_threshold"] == 0.70


def test_shipped_config_has_the_long_term_sleeve_off():
    from discovery import settings
    assert settings.long_term_sleeve_enabled(None) is False


# --- key safety -------------------------------------------------------------

CANARY = "CANARY-LONGTERM-KEY-MUST-NOT-APPEAR-7h6g5f"


def test_no_key_value_reaches_a_thesis(tmp_path, monkeypatch):
    """A rationale is council prose and bucketed labels, never a credential."""
    cfg = _cfg(tmp_path)
    monkeypatch.setenv("FINNHUB_API_KEY", CANARY)

    council = FakeCouncil(bias=0.6, confidence=0.85)
    monkeypatch.setattr(evaluate, "four_level_evaluator",
                        lambda **kw: (lambda s: evaluate.build_verdict(
                            symbol=s, council=council, dnn={}, whale={})))
    client = FakeClient(financials=_GOOD_FIN,
                        sentiment={"companyNewsScore": 0.5}, recs=[],
                        earnings=_EARNINGS_SOON)

    t = long_term.long_term_thesis({"symbol": "AAPL"}, client=client,
                                   cfg_path=cfg, now=NOW)
    assert CANARY not in str(t)
