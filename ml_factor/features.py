"""Canonical feature surface for the DNN advisory factor.

ONE definition, ONE builder, shared by training and serving. The set itself
lives in ml_factor/real_dataset.py (REAL_FEATURE_NAMES + _features_at) because
that is where the bar math lives. This module is the import surface the model
and the serving path use, so the names stay stable.

HISTORY (2026-07-18). The old `build_features(state)` built 10 features from a
serving-state dict while training used 6 different bar-derived features, and
four of the serving ten were constant defaults that never varied in
production. The constant `recent_winrate=0.5` alone moved the synthetic
champion's read from +0.03 to -0.33 on every evaluation. `build_features` is
GONE. Both paths now build through `features_at` over real bars, and a model
artifact records the signature it was trained with (ml_factor/model.py), which
serving verifies before scoring (ml_factor/factor.py).
"""
from __future__ import annotations

from .real_dataset import (FEATURE_SET_VERSION, N_REAL_FEATURES,
                           REAL_FEATURE_NAMES, _features_at, serve_window)

FEATURE_NAMES = REAL_FEATURE_NAMES
N_FEATURES = N_REAL_FEATURES

# The one builder. bars is an oldest-first list of dicts with high, low,
# close, ts. i is the index scored, using bars[:i+1] only (no lookahead).
features_at = _features_at

__all__ = ["FEATURE_NAMES", "N_FEATURES", "FEATURE_SET_VERSION",
           "features_at", "serve_window"]
