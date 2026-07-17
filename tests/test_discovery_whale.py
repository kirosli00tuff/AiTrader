"""Tests for whale activity as a Stage-A candidate-surfacing signal.

The claims that matter:
  * a strong whale signal RAISES an instrument's Stage-A rank and can surface it
    into the finalist set when its technicals alone would not have.
  * the whale weight is CONFIGURABLE and does NOT dominate at the default: a
    whale-only name still loses to a strong technical name.
  * whale STILL evaluates survivors in Stage C at its 0.35 cap. Surfacing did not
    replace evaluation. Same data, two jobs, deliberate.
  * a whale-surfaced candidate is TAGGED, and the tag is a counterfactual, not a
    threshold.
  * with the discovery flags off, none of it runs.

Mocked whale data throughout. No network.
"""
from __future__ import annotations

import logging
import os

import pytest
import yaml

from discovery import funnel, settings, whale_surfacer
from discovery.whale_surfacer import WhaleSurfacer, whale_component


# --- fixtures ---------------------------------------------------------------

def _whale(activity=0.9, bias=0.8, delayed=0, regime="accumulation") -> dict:
    """A whale signal dict in the shape whale_signal.WhaleSignal.to_dict emits."""
    return {"whale_bias": bias, "bias": bias, "whale_confidence": 0.7,
            "whale_flow_direction": "bullish" if bias > 0 else "bearish",
            "whale_activity_score": activity, "whale_follow_signal": 1,
            "whale_contradiction_flag": 0, "whale_regime_label": regime,
            "delayed_only": delayed}


def _snap(symbol: str, *, change_pct=3.0, price=100.0, high=103.0, low=99.0,
          whale=0.0, **kw) -> dict:
    s = {"symbol": symbol, "price": price, "change_pct": change_pct,
         "high": high, "low": low, "open": 100.0, "prev_close": 100.0,
         "whale_component": whale}
    s.update(kw)
    return s


def _cfg(tmp_path, **discovery) -> str:
    base = {
        "discovery_enabled": True,
        "long_term_sleeve_enabled": False,
        "crypto_universe": "BTC/USD",
        "equity_universe": "AAPL",
        "max_finalists": 12, "max_survivors": 5,
        "max_council_calls_per_pass": 5,
        "discovery_daily_council_budget": 12,
        "discovery_est_cost_per_call_usd": 0.04,
        "prescreen_min_score": 0.15,
        "stage_a_whale_weight": 0.15,
        "watchlist_max_size": 40, "watchlist_stale_hours": 48,
    }
    base.update(discovery)
    os.makedirs(str(tmp_path), exist_ok=True)
    p = os.path.join(str(tmp_path), "w.yaml")
    with open(p, "w", encoding="utf-8") as f:
        yaml.safe_dump({"discovery": base,
                        "council": {"council_min_confidence": 0.6},
                        "sleeves": {"research_conviction_threshold": 0.7}}, f)
    return p


# --- whale_component (pure) -------------------------------------------------

def test_strong_accumulation_scores_high():
    assert whale_component(_whale(activity=0.9, bias=0.9)) > 0.7


def test_no_signal_scores_zero():
    assert whale_component({}) == 0.0
    assert whale_component(None) == 0.0


def test_activity_below_the_floor_scores_zero():
    # Faint evidence is noise. Boosting on it would surface names for no reason.
    assert whale_component(_whale(activity=0.1, bias=0.9)) == 0.0


def test_directionless_flow_scores_zero():
    # Loud but with no direction is not a signal.
    assert whale_component(_whale(activity=0.95, bias=0.0)) == 0.0


def test_evidence_and_conviction_must_both_be_present():
    strong = whale_component(_whale(activity=0.9, bias=0.9))
    weak_evidence = whale_component(_whale(activity=0.4, bias=0.9))
    weak_conviction = whale_component(_whale(activity=0.9, bias=0.4))
    assert strong > weak_evidence
    assert strong > weak_conviction


def test_distribution_surfaces_at_half_weight():
    """A name whales are dumping is worth a look, but less than accumulation."""
    acc = whale_component(_whale(activity=0.9, bias=0.8))
    dist = whale_component(_whale(activity=0.9, bias=-0.8, regime="distribution"))
    assert dist == pytest.approx(acc * 0.5, abs=1e-3)
    assert dist > 0  # still surfaces: a sharp exit is information


def test_delayed_only_evidence_is_downweighted():
    """13F lags ~45 days: real context, but not live flow."""
    live = whale_component(_whale(activity=0.9, bias=0.8, delayed=0))
    delayed = whale_component(_whale(activity=0.9, bias=0.8, delayed=1))
    assert delayed < live
    assert delayed == pytest.approx(live * 0.6, abs=1e-3)


def test_component_stays_in_range():
    for a in (0.0, 0.5, 1.0):
        for b in (-1.0, 0.0, 1.0):
            assert 0.0 <= whale_component(_whale(activity=a, bias=b)) <= 1.0


def test_malformed_signal_never_raises():
    assert whale_component({"whale_activity_score": "nonsense"}) == 0.0
    assert whale_component({"whale_activity_score": 0.9,
                            "whale_bias": None}) == 0.0


# --- the surfacer (cache, budget, degradation) ------------------------------

def test_surfacer_caches_so_a_pass_does_not_refetch():
    calls = []

    def scorer(sym):
        calls.append(sym)
        return _whale()

    w = WhaleSurfacer(scorer=scorer)
    w.signal_for("AAPL")
    w.signal_for("AAPL")
    # 13F cannot change within an hour, so a second fetch would buy nothing.
    assert calls == ["AAPL"]
    assert w.cache_hits == 1


def test_surfacer_respects_its_per_pass_fetch_budget():
    calls = []

    def scorer(sym):
        calls.append(sym)
        return _whale()

    w = WhaleSurfacer(scorer=scorer, fetch_budget=2)
    for s in ("A", "B", "C", "D"):
        w.signal_for(s)
    # Bounded: SEC EDGAR fair access is finite, and a pass must not stall.
    assert len(calls) == 2
    assert w.budget_skips == 2
    # Past the budget a symbol scores 0, which is just the pre-whale ranking.
    assert w.signal_for("E") == {}


def test_surfacer_budget_resets_between_passes_but_the_cache_survives():
    calls = []
    w = WhaleSurfacer(scorer=lambda s: calls.append(s) or _whale(),
                      fetch_budget=1)
    w.signal_for("A")
    w.signal_for("B")           # over budget
    assert len(calls) == 1
    w.reset_pass()
    w.signal_for("B")           # budget refreshed
    assert len(calls) == 2
    w.signal_for("A")           # still cached, no refetch
    assert len(calls) == 2


def test_a_broken_whale_source_degrades_to_no_boost():
    def boom(_sym):
        raise RuntimeError("SEC EDGAR down")

    w = WhaleSurfacer(scorer=boom)
    # An advisory input must never break a pass. No data means no boost.
    assert w.signal_for("AAPL") == {}
    assert whale_component(w.signal_for("AAPL")) == 0.0


def test_surfacing_label_reads_plainly():
    assert whale_surfacer.surfacing_label(_whale()) == "whale accumulation"
    assert whale_surfacer.surfacing_label(
        _whale(delayed=1)) == "whale accumulation (delayed)"
    assert whale_surfacer.surfacing_label({}) == ""


# --- Stage A: whale raises rank ---------------------------------------------

def test_whale_raises_an_instruments_prescreen_score():
    quiet = _snap("A", change_pct=1.0, high=100.5, low=99.5, whale=0.0)
    same_but_whales = {**quiet, "whale_component": 0.9}
    without, _ = funnel.prescreen_score(quiet, 0.15)
    with_whale, _ = funnel.prescreen_score(same_but_whales, 0.15)
    assert with_whale > without


def test_whale_can_surface_a_name_the_technicals_would_have_missed():
    """The point of the whole feature, in one test.

    The realistic case is a BORDERLINE name: one sitting just outside the cut on
    its technicals, which whale accumulation lifts over the line. That is what
    "an instrument can enter the funnel because whales moved into it" means at a
    moderate weight. Whale deliberately CANNOT rescue a dead-flat name from far
    down the ranking, which the dominance test below pins.
    """
    # Three names with similar, middling technicals. BORDER is fractionally the
    # weakest, so on technicals alone it loses the last finalist slot.
    snaps = [
        _snap("TECH1", change_pct=2.2, high=102.0, low=99.0),
        _snap("TECH2", change_pct=2.1, high=101.9, low=99.0),
        _snap("BORDER", change_pct=2.0, high=101.8, low=99.0, whale=0.9),
    ]

    # Without whale, BORDER misses a 2-name finalist set.
    no_whale, _ = funnel.prescreen(snaps, max_finalists=2, min_score=0.05,
                                   whale_weight=0.0)
    assert [f.symbol for f in no_whale] == ["TECH1", "TECH2"]

    # With whale, BORDER is lifted in, and it is tagged as whale-surfaced.
    with_whale, _ = funnel.prescreen(snaps, max_finalists=2, min_score=0.05,
                                     whale_weight=0.15)
    surfaced = {f.symbol: f for f in with_whale}
    assert "BORDER" in surfaced
    assert surfaced["BORDER"].whale_surfaced is True
    # And it displaced the name it out-ranked, rather than widening the set.
    assert len(with_whale) == 2


def test_whale_cannot_rescue_a_dead_name_from_far_down_the_ranking():
    """The other half of the same coin: whale lifts a borderline name, it does
    not resurrect one. A moderate weight has to mean something."""
    snaps = [_snap(f"TECH{i}", change_pct=4.0 - i * 0.1) for i in range(10)]
    snaps.append(_snap("DEAD", change_pct=0.4, high=100.3, low=99.8, whale=0.95))

    finalists, _ = funnel.prescreen(snaps, max_finalists=3, min_score=0.05,
                                    whale_weight=0.15)
    # Maximum whale activity still does not beat ten strongly trending names.
    assert "DEAD" not in [f.symbol for f in finalists]


def test_a_technically_surfaced_name_is_not_tagged_whale_surfaced():
    """The tag is a counterfactual: it must not fire for a name that would have
    made the cut anyway, even when that name also has whale activity."""
    snaps = [_snap("LOUD", change_pct=5.0, high=106.0, low=100.0, whale=0.9),
             _snap("Q1", change_pct=0.1, high=100.05, low=99.95),
             _snap("Q2", change_pct=0.1, high=100.05, low=99.95)]
    finalists, _ = funnel.prescreen(snaps, max_finalists=1, min_score=0.0,
                                    whale_weight=0.15)
    assert finalists[0].symbol == "LOUD"
    # It had whale activity, but it did not NEED it. Not whale-surfaced.
    assert finalists[0].whale_surfaced is False


def test_nothing_is_whale_surfaced_when_the_weight_is_zero():
    snaps = [_snap("A", whale=0.99), _snap("B", whale=0.99)]
    finalists, _ = funnel.prescreen(snaps, max_finalists=2, min_score=0.0,
                                    whale_weight=0.0)
    assert all(f.whale_surfaced is False for f in finalists)


# --- the weight is configurable and does not dominate -----------------------

def test_whale_weight_zero_reproduces_the_pre_whale_score_exactly():
    """The normalization must be a no-op at weight 0, or the change would not be
    inert for anyone who does not opt in."""
    snap = _snap("A", change_pct=3.0, sentiment_score=0.8, native_strength=0.5,
                 whale=0.9)
    score, comps = funnel.prescreen_score(snap, 0.0)
    # Recompute the pre-whale formula by hand from the same components.
    expected = (0.30 * comps["momentum"] + 0.25 * comps["volatility"] +
                0.15 * comps["gap"] + 0.15 * comps["sentiment"] +
                0.15 * comps["native"])
    assert score == pytest.approx(round(expected, 4), abs=1e-4)


def test_whale_does_not_dominate_at_the_default_weight():
    """A whale-only name must still lose to a strong technical name."""
    whale_only = _snap("WHALE", change_pct=0.0, high=100.01, low=100.0,
                       whale=1.0)
    technical = _snap("TECH", change_pct=5.0, high=106.0, low=100.0, whale=0.0)
    w, _ = funnel.prescreen_score(whale_only, 0.15)
    t, _ = funnel.prescreen_score(technical, 0.15)
    assert t > w, "whale alone must not outrank strong price and volume"


def test_a_higher_weight_surfaces_harder():
    """The operator can tune it without touching code."""
    snap = _snap("A", change_pct=0.5, high=100.2, low=99.9, whale=0.9)
    low = funnel.prescreen_score(snap, 0.05)[0]
    mid = funnel.prescreen_score(snap, 0.15)[0]
    high = funnel.prescreen_score(snap, 0.60)[0]
    assert low < mid < high


def test_the_score_stays_bounded_at_any_weight():
    snap = _snap("A", change_pct=99.0, high=200.0, low=1.0, whale=1.0,
                 sentiment_score=1.0, native_strength=1.0)
    for w in (0.0, 0.15, 1.0, 5.0):
        score, _ = funnel.prescreen_score(snap, w)
        assert 0.0 <= score <= 1.0


def test_the_default_weight_is_moderate():
    """Level with sentiment and native, below momentum and volatility."""
    w = settings.stage_a_whale_weight(None)
    assert w == 0.15
    assert w == funnel._W_SENTIMENT == funnel._W_NATIVE
    assert w < funnel._W_MOMENTUM
    assert w < funnel._W_VOLATILITY
    # One sixth of the total: it can lift, it cannot dominate.
    assert w / (funnel._W_FIXED_TOTAL + w) < 0.2


def test_the_weight_is_configurable(tmp_path):
    cfg = _cfg(tmp_path, stage_a_whale_weight=0.4)
    assert settings.stage_a_whale_weight(cfg) == 0.4


def test_python_and_cpp_whale_weight_defaults_agree():
    """Two declarations of one contract must not drift."""
    import re
    with open("config/config.hpp", encoding="utf-8") as f:
        block = f.read().split("struct DiscoveryConfig {")[1].split("};")[0]
    m = re.search(r"\bstage_a_whale_weight\s*=\s*([^;]+);", block)
    assert m and float(m.group(1)) == settings._DEFAULTS["stage_a_whale_weight"]


# --- Stage C evaluation is UNCHANGED ----------------------------------------

class _Council:
    bias, confidence, edge = 0.6, 0.8, 0.05
    agreement_count, verdict, per_model = 3, "buy", []


def test_whale_still_evaluates_survivors_in_stage_c():
    """Surfacing did NOT replace evaluation. Whale still informs the verdict."""
    from discovery import evaluate
    confirming = evaluate.build_verdict(
        symbol="A", council=_Council(), dnn={}, whale={"whale_bias": 1.0},
        conviction_floor=0.6)
    contradicting = evaluate.build_verdict(
        symbol="A", council=_Council(), dnn={}, whale={"whale_bias": -1.0},
        conviction_floor=0.6)
    # The whale layer moved the conviction, so it is still in the ensemble.
    assert confirming["conviction"] > contradicting["conviction"]
    assert confirming["whale_bias"] == 1.0


def test_stage_c_whale_stays_advisory_and_bounded():
    """Level 4 keeps its posture: it can never flip a verdict on its own."""
    from discovery import evaluate
    v = evaluate.build_verdict(symbol="A", council=_Council(), dnn={},
                               whale={"whale_bias": -1.0}, conviction_floor=0.6)
    assert v["direction"] == "long"     # still the council's call
    assert abs(v["advisory_adjustment"]) <= evaluate._ADVISORY_ADJUST_MAX


def test_the_whale_position_scale_cap_is_still_035():
    """The 0.35 sizing cap is a Level-4 value and this build did not touch it."""
    with open("config/default_config.yaml", encoding="utf-8") as f:
        cfg = yaml.safe_load(f)
    assert cfg["sizing"]["whale_position_scale_cap"] == 0.35


def test_whale_serves_both_stages_from_the_same_data():
    """Surfacing and evaluation read the same WhaleSignal shape. That is the
    deliberate design, not a duplication bug."""
    from discovery import evaluate
    sig = _whale(activity=0.9, bias=0.8)
    # Stage A reads it for surfacing.
    assert whale_component(sig) > 0
    # Stage C reads the SAME dict for evaluation, via the same keys.
    v = evaluate.build_verdict(symbol="A", council=_Council(), dnn={}, whale=sig,
                               conviction_floor=0.6)
    assert v["whale_bias"] == 0.8


# --- flags off ---------------------------------------------------------------

def test_the_shipped_config_keeps_discovery_off():
    # Whale surfacing lives entirely inside discovery, which ships disabled.
    # Reads the shipped config FILE. cfg_path=None layers .control/controls.json
    # over config by design (that is how an operator enables discovery), so None
    # answers "what did this machine's operator last toggle", not "what does the
    # repo ship". This went red the first time a real operator enabled discovery.
    assert settings.discovery_enabled("config/default_config.yaml") is False


def test_run_once_never_surfaces_when_discovery_is_off(tmp_path):
    from discovery import run
    cfg = _cfg(tmp_path, discovery_enabled=False)
    calls = []
    out = run.run_once("crypto", db_path=os.path.join(str(tmp_path), "x.db"),
                       cfg_path=cfg, client=object(), gate=object(),
                       evaluator=lambda s: calls.append(s), force=True)
    assert out["status"] == "disabled"
    assert calls == []


# --- key safety -------------------------------------------------------------

def test_no_key_value_is_logged_by_the_surfacer(caplog):
    canary = "CANARY-WHALE-KEY-MUST-NOT-APPEAR-5t4r3e"
    caplog.set_level(logging.DEBUG, logger="discovery.whale")

    def boom(_sym):
        raise RuntimeError(f"failed with key {canary}")

    w = WhaleSurfacer(scorer=boom)
    w.signal_for("AAPL")
    # The handler logs the symbol only, never the exception text.
    assert canary not in caplog.text
