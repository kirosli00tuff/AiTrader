"""Feature engineering for the DNN/RL advisory factor.

Maps a raw market-state dict into the fixed-length feature vector the model
consumes. Feature order is stable (FEATURE_NAMES) so saved models stay valid.
"""
from __future__ import annotations

import math

FEATURE_NAMES = [
    "ret_1",            # last-interval return
    "ret_5",            # multi-horizon return
    "volatility",       # rolling vol regime proxy
    "spread_rel",       # relative spread (liquidity)
    "imbalance",        # order-book imbalance [-1,1]
    "catalyst",         # news/catalyst score [-1,1]
    "time_of_day",      # [0,1)
    "recent_winrate",   # recent performance feature [0,1]
    "streak",           # signed recent streak, scaled
    "drawdown",         # current drawdown [0,1]
]

N_FEATURES = len(FEATURE_NAMES)


def build_features(state: dict) -> list[float]:
    """Build a fixed-length feature vector from a (possibly partial) state."""
    price = float(state.get("price", 1.0)) or 1.0
    spread = float(state.get("spread", price * 0.001))
    feats = [
        float(state.get("ret_1", state.get("ret_5", 0.0))),
        float(state.get("ret_5", 0.0)),
        float(state.get("volatility", 0.0)),
        spread / price,
        float(state.get("imbalance", 0.0)),
        float(state.get("catalyst", 0.0)),
        float(state.get("time_of_day", 0.5)),
        float(state.get("recent_winrate", 0.5)),
        math.tanh(float(state.get("streak", 0.0)) / 3.0),
        float(state.get("drawdown", 0.0)),
    ]
    return feats
