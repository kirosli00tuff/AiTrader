"""Council cost cuts (Task 5/8): risk pre-check + market-hours skips.

Both fire in the Python ``consensus`` pipeline BEFORE the Flash gate and the
providers, so a skipped setup costs nothing. No network: providers/gate are
test doubles that ASSERT they are never called on a skip path.
"""
import pytest

from llm_consensus import GateDecision, consensus
from llm_consensus.verdicts import ModelVerdict, bias_to_verdict


class _MustNotRunProvider:
    name = "expensive"
    weight = 1.0

    def score(self, state):
        raise AssertionError("provider must not run on a cost-cut skip path")


class _ExplodingGate:
    """The skip must happen BEFORE the Flash gate, so this must never be called."""

    def should_review(self, state):
        raise AssertionError("Flash gate must not run on a cost-cut skip path")


class _RecordingProvider:
    name = "p"
    weight = 1.0

    def __init__(self):
        self.ran = False

    def score(self, state):
        self.ran = True
        return ModelVerdict(model="p", bias=0.5, confidence=0.7, edge=0.03,
                            verdict=bias_to_verdict(0.5), source="mock")


class _ProceedGate:
    def should_review(self, state):
        return GateDecision(True, "worth a review", "test-gate", "real")


# --- Cost cut 1: risk pre-check --------------------------------------------- #

def test_risk_precheck_skip_fires_before_any_provider_or_gate():
    res = consensus(
        {"symbol": "SPY", "risk_precheck_block": True,
         "risk_precheck_reason": "daily loss halt"},
        providers=[_MustNotRunProvider()], gate=_ExplodingGate())
    assert res.per_model == []                    # no provider ran => no cost
    assert res.bias == 0.0 and res.confidence == 0.0 and res.edge == 0.0
    assert res.gate["proceed"] is False
    assert res.gate["model"] == "risk_precheck"
    assert "daily loss halt" in res.gate["reason"]


def test_no_risk_precheck_flag_does_not_skip():
    prov = _RecordingProvider()
    # crypto symbol so the market-hours cut can't fire either; no risk flag set.
    res = consensus({"symbol": "BTC-USD", "ret_5": 0.02},
                    providers=[prov], gate=_ProceedGate())
    assert prov.ran is True
    assert res.gate["model"] != "risk_precheck"


# --- Cost cut 2: market-hours skip (equities only) -------------------------- #

def test_market_hours_skip_fires_for_equity_outside_hours():
    res = consensus(
        {"symbol": "SPY", "market_open": False},
        providers=[_MustNotRunProvider()], gate=_ExplodingGate())
    assert res.per_model == []
    assert res.gate["proceed"] is False
    assert res.gate["model"] == "market_hours"


def test_market_hours_never_skips_crypto():
    prov = _RecordingProvider()
    # Crypto with the market flagged CLOSED must still run (24/7).
    res = consensus({"symbol": "BTC-USD", "market_open": False},
                    providers=[prov], gate=_ProceedGate())
    assert prov.ran is True
    assert res.gate["model"] != "market_hours"


def test_market_hours_does_not_skip_equity_during_open_hours():
    prov = _RecordingProvider()
    res = consensus({"symbol": "QQQ", "market_open": True},
                    providers=[prov], gate=_ProceedGate())
    assert prov.ran is True
    assert res.gate["model"] != "market_hours"


def test_market_hours_disabled_by_config_does_not_skip(tmp_path):
    cfg = tmp_path / "off.yaml"
    cfg.write_text("engine:\n  equities_market_hours_only: false\n")
    prov = _RecordingProvider()
    res = consensus({"symbol": "SPY", "market_open": False},
                    providers=[prov], gate=_ProceedGate(), cfg_path=str(cfg))
    assert prov.ran is True                       # flag off => no market-hours skip
    assert res.gate["model"] != "market_hours"
