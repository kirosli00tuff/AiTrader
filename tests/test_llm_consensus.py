"""Tests for the multi-LLM consensus advisory service."""
from llm_consensus.consensus import (
    bias_to_verdict, consensus, default_providers, MockLLMProvider,
)


def test_bias_to_verdict_buckets():
    assert bias_to_verdict(0.9) == "strong_buy"
    assert bias_to_verdict(-0.9) == "strong_sell"
    assert bias_to_verdict(0.0) in {"hold", "neutral"}


def test_consensus_is_deterministic():
    state = {"symbol": "BTC-USD", "ret_5": 0.02, "imbalance": 0.3, "catalyst": 0.4}
    a = consensus(state).to_dict()
    b = consensus(state).to_dict()
    assert a == b


def test_consensus_output_shape_and_ranges():
    state = {"symbol": "AAPL", "ret_5": 0.01, "imbalance": 0.1, "catalyst": 0.2}
    res = consensus(state)
    d = res.to_dict()
    for key in ("bias", "confidence", "edge", "verdict", "agreement_count", "per_model"):
        assert key in d
    assert -1.0 <= d["bias"] <= 1.0
    assert 0.0 <= d["confidence"] <= 1.0
    assert d["edge"] >= 0.0
    assert len(d["per_model"]) == 3


def test_agreement_count_bounds():
    state = {"symbol": "X", "ret_5": 0.05, "imbalance": 0.5, "catalyst": 0.5}
    res = consensus(state)
    assert 0 <= res.agreement_count <= len(res.per_model)


def test_strong_bull_state_leans_buy():
    bull = {"symbol": "BTC-USD", "ret_5": 0.08, "imbalance": 0.8, "catalyst": 0.9}
    res = consensus(bull)
    assert res.bias > 0
    assert res.verdict in {"buy", "strong_buy"}


def test_custom_providers_respected():
    state = {"symbol": "Z", "ret_5": 0.0}
    providers = [MockLLMProvider(name="only", weight=1.0, skew=0.5)]
    res = consensus(state, providers=providers)
    assert len(res.per_model) == 1
    assert res.per_model[0].model == "only"


def test_default_providers_named_for_cpp_factors():
    names = {p.name for p in default_providers()}
    assert {"llm_primary", "llm_secondary", "llm_tertiary"} <= names
