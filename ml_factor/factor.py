"""DNN/RL advisory factor serving entry point.

Loads the champion model (training + saving a tiny one on first use so the demo
always has a real model), scores a market state, and applies the advisory
sizing cap. Output fields match DNN_RL_DESIGN.md exactly.
"""
from __future__ import annotations

import os

from .features import build_features
from .model import DnnModel

_MODELS_DIR = os.path.join(os.path.dirname(__file__), "models")
_CHAMPION_PATH = os.path.join(_MODELS_DIR, "champion.npz")

_DEFAULT_SCALE_CAP = 0.5  # sizing.dnn_position_scale_cap

_cached: DnnModel | None = None


def load_champion() -> DnnModel:
    """Return the champion model, training + persisting a tiny one if absent."""
    global _cached
    if _cached is not None:
        return _cached
    os.makedirs(_MODELS_DIR, exist_ok=True)
    if os.path.exists(_CHAMPION_PATH):
        _cached = DnnModel.load(_CHAMPION_PATH)
    else:
        _cached = DnnModel.train_synthetic(model_id="dnn-0.1.0")
        _cached.save(_CHAMPION_PATH)
    return _cached


def score_state(state: dict, scale_cap: float = _DEFAULT_SCALE_CAP) -> dict:
    """Score a market state -> advisory DNN outputs (sizing hint capped).

    The position scale hint is hard-capped here so the DNN can never request a
    size beyond its advisory cap; Layer-1 risk still bounds everything further.
    """
    model = load_champion()
    out = model.forward(build_features(state))
    out["dnn_position_scale_hint"] = round(
        min(out["dnn_position_scale_hint"], scale_cap), 4
    )
    out["model_id"] = model.model_id
    # Bridge-compatible aliases consumed by the C++ engine's generic reader.
    out["bias"] = out["dnn_action_bias"]
    out["confidence"] = out["dnn_confidence"]
    out["edge"] = out["dnn_expected_edge"]
    return out


if __name__ == "__main__":
    import json

    s = {"ret_5": 0.03, "volatility": 0.2, "imbalance": 0.4, "catalyst": 0.5,
         "price": 100, "spread": 0.1}
    print(json.dumps(score_state(s), indent=2))
