"""Tests for the whale / smart-money advisory module."""
from whale_signal.adapters import WhaleActivity, default_adapters
from whale_signal.scoring import score_whales, actor_usefulness, rank_actors
from whale_signal.service import whale_signal_for


def _act(source, entity, direction, value, delayed=False, symbol="BTC-USD"):
    return WhaleActivity(source=source, entity=entity, symbol=symbol,
                         direction=direction, value_usd=value, delayed=delayed,
                         ts="2026-06-29T00:00:00Z")


def test_signal_has_exact_named_fields():
    sig, acts = whale_signal_for("BTC-USD")
    d = sig.to_dict()
    for key in ("whale_bias", "whale_confidence", "whale_flow_direction",
                "whale_activity_score", "whale_follow_signal",
                "whale_contradiction_flag", "whale_regime_label"):
        assert key in d
    # bridge aliases
    assert d["bias"] == d["whale_bias"]
    assert d["confidence"] == d["whale_confidence"]


def test_offline_mock_produces_activity():
    # No keys in env -> adapters must mock, never raise.
    _sig, acts = whale_signal_for("AAPL")
    assert isinstance(acts, list)


def test_ranges_are_bounded():
    sig, _ = whale_signal_for("PRES-2028-YES", market_bias=0.2)
    d = sig.to_dict()
    assert -1.0 <= d["whale_bias"] <= 1.0
    assert 0.0 <= d["whale_confidence"] <= 1.0
    assert 0.0 <= d["whale_activity_score"] <= 1.0
    assert d["whale_follow_signal"] in (0, 1)
    assert d["whale_contradiction_flag"] in (0, 1)


def test_inflows_lean_bullish():
    acts = [_act("whale_alert", "useful-whale-1", "inflow", 5_000_000),
            _act("whale_alert", "useful-whale-2", "long", 8_000_000)]
    sig = score_whales(acts, "BTC-USD", min_actor_usefulness=0.0)
    assert sig.whale_bias >= 0
    assert sig.whale_flow_direction in {"bullish", "neutral"}


def test_delayed_only_is_downweighted():
    """13F-style delayed-only evidence should not produce a high-confidence
    actionable follow signal versus equivalent fresh evidence."""
    fresh = [_act("whale_alert", "w1", "inflow", 9_000_000, delayed=False, symbol="AAPL"),
             _act("whale_alert", "w2", "inflow", 9_000_000, delayed=False, symbol="AAPL")]
    delayed = [_act("sec_13f", "w1", "long", 9_000_000, delayed=True, symbol="AAPL"),
               _act("sec_13f", "w2", "long", 9_000_000, delayed=True, symbol="AAPL")]
    s_fresh = score_whales(fresh, "AAPL", min_actor_usefulness=0.0)
    s_delayed = score_whales(delayed, "AAPL", min_actor_usefulness=0.0)
    assert s_delayed.whale_confidence <= s_fresh.whale_confidence
    assert s_delayed.delayed_only == 1


def test_contradiction_flag_set_against_opposing_market_bias():
    acts = [_act("whale_alert", "w1", "outflow", 9_000_000),
            _act("whale_alert", "w2", "short", 9_000_000)]
    sig = score_whales(acts, "BTC-USD", market_bias=0.8,
                       min_actor_usefulness=0.0, contradiction_enabled=True)
    # whales bearish, market strongly bullish -> contradiction
    assert sig.whale_contradiction_flag == 1


def test_noisy_actors_filtered():
    ranked_all = rank_actors([_act("apify", "n", "long", 1.0)], min_usefulness=0.0)
    ranked_strict = rank_actors([_act("apify", "n", "long", 1.0)], min_usefulness=1.01)
    assert len(ranked_all) >= len(ranked_strict)


def test_actor_usefulness_bounded():
    u = actor_usefulness("some-actor")
    assert 0.0 <= u <= 1.0


def test_default_adapters_present():
    sources = {a.source for a in default_adapters()}
    assert {"apify", "whale_alert", "sec_13f"} <= sources
