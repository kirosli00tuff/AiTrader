"""RL advisory factor (Layer 3, DEFERRED — ships toggled OFF).

Package layout:
  config.py    -> rl_enabled / rl_min_real_fills getters + the 0.5 advisory cap
  service.py   -> score_rl() with disabled/mock/real fallbacks (no heavy deps)
  dataset.py   -> real-bar feature series + real-fill count (numpy)
  env.py       -> gymnasium TradingEnv (import rl_advisory.env directly)
  evaluate.py  -> walk-forward + deterministic-policy eval + champion gate
  train.py     -> PPO trainer with the real-fill gate (lazy torch/SB3)

Only ``config`` and ``service`` are re-exported here so ``import rl_advisory``
stays free of gymnasium/torch — the bridge (/score/rl) needs only ``score_rl``,
which never imports a heavy backend on its disabled/mock paths. Import
``rl_advisory.env`` / ``rl_advisory.train`` / ``rl_advisory.evaluate`` directly
when the RL backend is actually needed.
"""
from __future__ import annotations

from .config import (RL_ADVISORY_CAP, crypto_allow_short, rl_enabled,
                     rl_min_real_fills)
from .service import rl_ensemble_factor_names, score_rl

__all__ = [
    "RL_ADVISORY_CAP",
    "crypto_allow_short",
    "rl_enabled",
    "rl_min_real_fills",
    "score_rl",
    "rl_ensemble_factor_names",
]
