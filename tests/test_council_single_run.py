"""One council run per evaluation (2026-07-20).

A council-tier trading evaluation used to trigger a FULL council round per llm
slot: nine provider calls and three gate calls per evaluation. The round now
runs once, hoisted before the factor loop, and every slot carries the composed
verdict. These tests pin the structure in the C++ source, demonstrate both
shapes executably with counting stubs, and pin that the budget counter's unit
(one per evaluation) now equals one HTTP round. Per-provider transparency to
the composition and the persisted record is pinned by test_council_evidence.
No network, nothing binds.
"""
from __future__ import annotations

import os

from llm_consensus import consensus
from llm_consensus.gate import GateDecision
from llm_consensus.verdicts import ModelVerdict

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ENGINE = open(os.path.join(REPO, "core", "engine.cpp")).read()


def test_score_llm_string_lives_only_in_fetch_council():
    assert ENGINE.count('"/score/llm"') == 1
    body = ENGINE[ENGINE.index("Engine::fetch_council_verdict"):]
    body = body[:body.index("\n}")]
    assert '"/score/llm"' in body


def test_fetch_hoisted_once_before_the_factor_loop():
    # Exactly two occurrences: the definition and the single call site.
    assert ENGINE.count("fetch_council_verdict(") == 2
    gather = ENGINE[ENGINE.index("Engine::gather_factors"):]
    call = gather.index("fetch_council_verdict(")
    loop = gather.index("for (const auto& f : factors)")
    assert call < loop, "the one council round must precede the factor loop"


def test_discovery_stage_c_is_a_single_round():
    src = open(os.path.join(REPO, "discovery", "evaluate.py")).read()
    body = src[src.index("def _evaluate("):]
    body = body[:body.index("return _evaluate")]
    assert body.count("_consensus(") == 1


def test_budget_unit_matches_one_round_per_evaluation():
    src = open(os.path.join(REPO, "signal_engine", "council_gate.cpp")).read()
    assert src.count("++state.calls_today") == 1


class _CountingGate:
    def __init__(self):
        self.calls = 0

    def should_review(self, state):
        self.calls += 1
        return GateDecision(True, "counting", "stub", "real")


class _CountingProvider:
    def __init__(self, name, bias, conf):
        self.name, self.weight, self.calls = name, 0.2, 0
        self._bias, self._conf = bias, conf

    def score(self, state):
        self.calls += 1
        return ModelVerdict(model=self.name, bias=self._bias,
                            confidence=self._conf, edge=0.01, verdict="buy",
                            rationale="stub", source="real")


def _fresh_council():
    return (_CountingGate(), [
        _CountingProvider("llm_primary", 0.6, 0.6),
        _CountingProvider("llm_secondary", 0.0, 0.6),
        _CountingProvider("llm_tertiary", -0.5, 0.5)])


def test_shape_measured_old_three_rounds_new_one():
    state = {"symbol": "BTC/USD", "price": 100.0}
    # OLD engine shape: one full council round PER llm slot.
    gate, providers = _fresh_council()
    for _slot in ("llm_primary", "llm_secondary", "llm_tertiary"):
        consensus(state, providers=providers, gate=gate,
                  cfg_path="config/default_config.yaml")
    assert gate.calls == 3
    assert sum(p.calls for p in providers) == 9
    # NEW engine shape: one round per evaluation.
    gate, providers = _fresh_council()
    result = consensus(state, providers=providers, gate=gate,
                       cfg_path="config/default_config.yaml")
    assert gate.calls == 1
    assert sum(p.calls for p in providers) == 3
    # The composed verdict still follows the abstention rule: conviction among
    # directional voters, the hold abstains, agreement counts direction.
    assert result.directional_count == 2
    assert result.abstentions == 1
    assert len(result.per_model) == 3
    dwsum = 0.2 + 0.2
    expected_conf = (0.6 * 0.2 + 0.5 * 0.2) / dwsum
    assert abs(result.confidence - expected_conf) < 1e-9
