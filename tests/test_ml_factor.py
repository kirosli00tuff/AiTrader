"""Tests for the DNN/RL advisory factor: scoring, IO round-trip, sizing cap."""
import os

from ml_factor.factor import score_state, load_champion
from ml_factor.model import DnnModel
from ml_factor.features import build_features, N_FEATURES

_SCALE_CAP = 0.5

_STATE = {"symbol": "BTC-USD", "ret_5": 0.03, "volatility": 0.2, "imbalance": 0.4,
          "catalyst": 0.5, "price": 100, "spread": 0.1}


def test_features_have_fixed_width():
    feats = build_features(_STATE)
    assert len(feats) == N_FEATURES


def test_score_state_emits_named_fields():
    out = score_state(_STATE)
    for key in ("dnn_action_bias", "dnn_confidence", "dnn_expected_edge",
                "dnn_regime_label", "dnn_risk_flag", "dnn_position_scale_hint"):
        assert key in out
    # bridge aliases the C++ engine consumes. A synthetic-trained champion is
    # BENCHED (2026-07-18): the aliases are zero while the raw dnn_* outputs
    # stay visible. A real-trained champion serves the aliases unchanged.
    assert "benched" in out
    if out["benched"]:
        assert out["bias"] == 0.0
        assert out["confidence"] == 0.0
        assert out["edge"] == 0.0
        assert out["benched_reason"]
    else:
        assert out["bias"] == out["dnn_action_bias"]
        assert out["confidence"] == out["dnn_confidence"]
        assert out["edge"] == out["dnn_expected_edge"]


def test_scale_hint_is_capped():
    out = score_state(_STATE)
    assert out["dnn_position_scale_hint"] <= _SCALE_CAP + 1e-9


def test_output_ranges():
    out = score_state(_STATE)
    assert -1.0 <= out["dnn_action_bias"] <= 1.0
    assert 0.0 <= out["dnn_confidence"] <= 1.0


def test_champion_is_loadable_and_has_id():
    model = load_champion()
    assert model.model_id
    assert isinstance(model, DnnModel)


def test_model_save_load_roundtrip(tmp_path):
    model = load_champion()
    path = os.path.join(tmp_path, "rt.npz")
    model.save(path)
    assert os.path.exists(path)
    reloaded = DnnModel.load(path)
    assert reloaded.model_id == model.model_id
    a = model.forward(build_features(_STATE))
    b = reloaded.forward(build_features(_STATE))
    assert a["dnn_action_bias"] == b["dnn_action_bias"]
    assert a["dnn_confidence"] == b["dnn_confidence"]


def test_scoring_is_deterministic():
    assert score_state(_STATE)["dnn_action_bias"] == score_state(_STATE)["dnn_action_bias"]
