"""Holds abstain from the directional vote, and the synthetic DNN is benched.

Mocked providers only. No network, no real provider, loopback untouched.

The 12 historical discovery verdicts are the spec: every directional read was
diluted below the 0.60 floor by confident holds, every floor-clearing read was
flat, and the synthetic DNN's constant negative was the deciding vote. Each
test pins one of the ways that must now be impossible.
"""
from __future__ import annotations

import json
import sqlite3
from types import SimpleNamespace

import pytest

from discovery.evaluate import build_verdict
from llm_consensus import consensus
from llm_consensus.gate import AlwaysProceedGate


class _Provider:
    """Stub provider with a fixed verdict. Mirrors the LLMProvider surface the
    ensemble reads: .weight and .score(state)."""

    def __init__(self, name, bias, conf, weight=0.2, edge=0.01):
        self.name = name
        self.weight = weight
        verdict = "buy" if bias > 0 else ("sell" if bias < 0 else "hold")
        self._v = SimpleNamespace(model=name, bias=bias, confidence=conf,
                                  edge=edge, verdict=verdict, rationale="",
                                  source="mock", model_id="stub")

    def score(self, state):
        return self._v


_STATE = {"symbol": "BTC/USD", "venue": "alpaca", "price": 100.0,
          "ret_5": 0.02, "volatility": 0.05}


def _run(providers):
    return consensus(_STATE, providers=providers, gate=AlwaysProceedGate())


# --- Task 1: holds abstain, conviction over directional voters only ----------

def test_one_buy_two_holds_yields_the_voters_conviction():
    # THE historical case (INJ/USD pass 11): buy 0.56 + holds 0.60/0.50 used
    # to average to 0.56 bias 0.27. Now the holds abstain: the read carries
    # the directional voter's own conviction, full bias, and two abstentions.
    r = _run([_Provider("llm_primary", 0.56, 0.56, weight=0.27),
              _Provider("llm_secondary", 0.0, 0.60, weight=0.18),
              _Provider("llm_tertiary", 0.0, 0.50, weight=0.12)])
    assert r.directional_count == 1
    assert r.abstentions == 2
    assert r.confidence == pytest.approx(0.56)
    assert r.bias == pytest.approx(0.56)
    # One seller plus two holds used to record agreement 3 (the sign test
    # counted bias 0.0 as -1). Directional voters only now.
    assert r.agreement_count == 1
    assert len(r.per_model) == 3  # raw outputs stay complete


def test_all_holds_are_flat_at_zero_conviction():
    # Confident holds (LDO 0.6937 historically) no longer manufacture
    # conviction: with zero directional voters there is nothing to be
    # convinced of.
    r = _run([_Provider("llm_primary", 0.0, 0.72, weight=0.27),
              _Provider("llm_secondary", 0.0, 0.55, weight=0.18),
              _Provider("llm_tertiary", 0.0, 0.85, weight=0.12)])
    assert r.directional_count == 0
    assert r.abstentions == 3
    assert r.bias == 0.0
    assert r.confidence == 0.0
    assert r.verdict == "hold"


def test_two_directional_voters_weight_normally():
    # Abstention does not change the math AMONG directional voters.
    r = _run([_Provider("llm_primary", 0.6, 0.7, weight=0.27),
              _Provider("llm_secondary", -0.5, 0.5, weight=0.18),
              _Provider("llm_tertiary", 0.0, 0.9, weight=0.12)])
    dw = 0.27 + 0.18
    assert r.confidence == pytest.approx((0.7 * 0.27 + 0.5 * 0.18) / dw)
    assert r.bias == pytest.approx((0.6 * 0.27 - 0.5 * 0.18) / dw)
    assert r.directional_count == 2
    assert r.abstentions == 1
    assert r.agreement_count == 1  # only the buyer agrees with net long


# --- Task 2: min_directional_votes gates the verdict -------------------------

def _council(bias, conf, directional, abstained, agreement=1):
    return SimpleNamespace(bias=bias, confidence=conf, edge=0.01,
                           verdict="buy" if bias > 0 else "hold",
                           agreement_count=agreement, per_model=[],
                           directional_count=directional,
                           abstentions=abstained)


def test_single_convinced_voter_passes_at_min_one():
    v = build_verdict(symbol="X/USD", council=_council(0.65, 0.65, 1, 2),
                      dnn={}, whale={}, conviction_floor=0.60,
                      min_directional=1)
    assert v["verdict"] == "buy"
    assert v["conviction"] == pytest.approx(0.65)
    assert v["directional_count"] == 1
    assert v["abstentions"] == 2


def test_min_directional_two_blocks_the_single_voter():
    v = build_verdict(symbol="X/USD", council=_council(0.65, 0.65, 1, 2),
                      dnn={}, whale={}, conviction_floor=0.60,
                      min_directional=2)
    assert v["verdict"] == "avoid"


def test_floor_still_applies_to_directional_conviction():
    # A lone voter at 0.56 (every historical directional read) still fails
    # the 0.60 floor: min_directional_votes never waives the floor.
    v = build_verdict(symbol="X/USD", council=_council(0.56, 0.56, 1, 2),
                      dnn={}, whale={}, conviction_floor=0.60,
                      min_directional=1)
    assert v["verdict"] == "avoid"


def test_all_hold_is_avoid_regardless_of_conviction():
    # Adversarial: even a council object claiming high confidence with no
    # direction stays avoid.
    v = build_verdict(symbol="X/USD", council=_council(0.0, 0.90, 0, 3, 0),
                      dnn={}, whale={}, conviction_floor=0.60,
                      min_directional=1)
    assert v["verdict"] == "avoid"
    assert v["direction"] == "flat"


def test_min_directional_votes_is_configurable():
    from llm_consensus.config_access import min_directional_votes
    assert min_directional_votes() == 1  # shipped value, this evaluation period


# --- Task 4: the synthetic-trained DNN is benched ----------------------------

def _registry_db(tmp_path, model_id=None, provenance=None):
    db = tmp_path / "reg.db"
    conn = sqlite3.connect(db)
    conn.execute(
        "CREATE TABLE model_registry (id INTEGER PRIMARY KEY AUTOINCREMENT,"
        " ts TEXT NOT NULL, model_id TEXT NOT NULL, role TEXT NOT NULL,"
        " metrics_json TEXT, notes TEXT)")
    if model_id is not None:
        conn.execute(
            "INSERT INTO model_registry(ts, model_id, role, metrics_json)"
            " VALUES('2026-07-18T00:00:00Z', ?, 'champion', ?)",
            (model_id, json.dumps({"provenance": provenance})))
    # Serving now builds features from the symbol's real bars in the SAME DB
    # (the unified pipeline), so the bench tests seed a warm bar window.
    conn.execute(
        "CREATE TABLE bars (venue TEXT, symbol TEXT, timeframe TEXT,"
        " timestamp TEXT, open REAL, high REAL, low REAL, close REAL,"
        " volume REAL, source TEXT DEFAULT 'unknown')")
    price = 100.0
    for i in range(40):
        price *= 1.0 + (0.002 if i % 3 else -0.001)
        conn.execute(
            "INSERT INTO bars VALUES('alpaca','BTC/USD','5min',?,?,?,?,?,?,"
            "'backfill')",
            (f"2026-07-18T{(i // 12):02d}:{(i % 12) * 5:02d}:00Z",
             price * 0.999, price * 1.004, price * 0.996, price, 10.0))
    conn.commit()
    conn.close()
    return str(db)


def _fresh_score(monkeypatch, db):
    from ml_factor import factor
    monkeypatch.setenv("MAL_DB_PATH", db)
    monkeypatch.setattr(factor, "_bench_cache", None)
    return factor.score_state({"symbol": "BTC/USD", "price": 100.0,
                               "ret_5": 0.02, "volatility": 0.05})


def test_synthetic_champion_contributes_exactly_zero(tmp_path, monkeypatch):
    # No champion row in the registry: the serving artifact is the synthetic
    # bootstrap, so the factor is benched and the composed aliases are zero
    # while the raw model outputs stay visible.
    db = _registry_db(tmp_path)
    out = _fresh_score(monkeypatch, db)
    assert out["benched"] is True
    assert "pending real training" in out["benched_reason"]
    assert out["bias"] == 0.0
    assert out["confidence"] == 0.0
    assert out["edge"] == 0.0
    # ABSENT, not uncertain: a benched factor reports it did NOT participate,
    # so the engine drops it from the confidence denominator instead of
    # averaging in a confident zero.
    assert out["participating"] is False
    # Raw stays visible and the model really scored: the confidence head is
    # structurally positive (softmax max_p >= 0.2), so a served raw read is
    # provably distinct from the zeroed unavailable payload.
    assert out["available"] is True
    assert out["dnn_confidence"] > 0.0


def test_synthetic_provenance_champion_is_benched(tmp_path, monkeypatch):
    from ml_factor import factor
    db = _registry_db(tmp_path, model_id=factor.load_champion().model_id,
                      provenance="synthetic")
    out = _fresh_score(monkeypatch, db)
    assert out["benched"] is True


def test_real_trained_champion_contributes_normally(tmp_path, monkeypatch):
    from ml_factor import factor
    db = _registry_db(tmp_path, model_id=factor.load_champion().model_id,
                      provenance="real-data")
    out = _fresh_score(monkeypatch, db)
    assert out["benched"] is False
    assert out["participating"] is True
    assert out["bias"] == out["dnn_action_bias"]
    assert out["confidence"] == out["dnn_confidence"]


def test_registry_champion_artifact_mismatch_is_benched(tmp_path, monkeypatch):
    # A real-data registry row whose model_id is NOT the serving artifact must
    # bench: the promoted model is not the one answering.
    db = _registry_db(tmp_path, model_id="dnn-real-9.9.9",
                      provenance="real-data")
    out = _fresh_score(monkeypatch, db)
    assert out["benched"] is True
    assert "does not match" in out["benched_reason"]


def test_benched_is_distinct_from_operator_disabled(tmp_path, monkeypatch):
    # Benched: the service answers, raw outputs flow, aliases are zero, and
    # the payload SAYS benched with a reason. An operator-disabled layer never
    # reaches the service at all (the engine drops the factor), so the marker
    # of the benched state is the flagged, reasoned, zeroed RESPONSE.
    db = _registry_db(tmp_path)
    out = _fresh_score(monkeypatch, db)
    assert out["benched"] is True
    assert out["benched_reason"]
    assert out["model_id"]  # the model still identifies itself
    assert "dnn_regime_label" in out  # full raw surface still served


def test_discovery_conviction_with_benched_dnn_keeps_council_read():
    # The ADA/USD case: council 0.6026 was dragged to 0.5366 by dnn -0.32.
    # A benched dnn (bias 0) leaves the whale-only adjustment, so the council
    # read survives.
    v = build_verdict(symbol="ADA/USD", council=_council(0.55, 0.6026, 1, 2),
                      dnn={"bias": 0.0}, whale={"whale_bias": 0.0},
                      conviction_floor=0.60, min_directional=1)
    assert v["conviction"] == pytest.approx(0.6026)
    assert v["verdict"] == "buy"
