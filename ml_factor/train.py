"""Train / (re)version the DNN advisory model and ship a tiny champion.

Run directly to (re)generate ml_factor/models/champion.npz:
    python -m ml_factor.train

In the continuous loop this would consume logged paper outcomes; here it trains
the reproducible synthetic Stage-A model so the demo emits real signals offline.
"""
from __future__ import annotations

import os

from .factor import _CHAMPION_PATH, _MODELS_DIR
from .model import DnnModel


def train_and_save(model_id: str = "dnn-0.1.0") -> str:
    os.makedirs(_MODELS_DIR, exist_ok=True)
    model = DnnModel.train_synthetic(model_id=model_id)
    model.save(_CHAMPION_PATH)
    return _CHAMPION_PATH


if __name__ == "__main__":
    path = train_and_save()
    print(f"Champion model written to {path}")
