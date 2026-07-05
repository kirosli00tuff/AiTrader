"""Gymnasium trading environment for the RL advisory factor (Task 4).

A minimal, deterministic single-instrument env over a precomputed real-bar
feature series (see rl_advisory/dataset.py). Advisory only — this env trains a
CHALLENGER; nothing here can place a live order or bypass Layer-1 risk.

Observation : flattened rolling window of per-bar features + a 3-way position
              one-hot (flat / long / short).
Actions     : Discrete(3) -> flat, long, short. Equities are long-only, so a
              short action is clamped to flat when ``long_only`` is set.
Reward      : realised step PnL  -  per-trade transaction cost  -  drawdown
              penalty. The transaction cost term is MANDATORY (charged on every
              position change) so the policy cannot churn for free.

Depends only on gymnasium + numpy (both light); the PPO backend (torch /
stable-baselines3) is imported lazily by rl_advisory/train.py, never here.
"""
from __future__ import annotations

import gymnasium as gym
import numpy as np
from gymnasium import spaces

# Discrete action -> target unit position.
ACTION_FLAT, ACTION_LONG, ACTION_SHORT = 0, 1, 2
_ACTION_TO_POSITION = {ACTION_FLAT: 0, ACTION_LONG: 1, ACTION_SHORT: -1}

# Defaults (overridable per instance). Transaction cost is a fraction of notional
# charged per unit of position change; drawdown penalty scales the running DD.
DEFAULT_TXN_COST_RATE = 0.0005     # 5 bps per unit position change
DEFAULT_DRAWDOWN_PENALTY = 0.1
DEFAULT_WINDOW = 16


class TradingEnv(gym.Env):
    """Deterministic gym env over a real-bar feature series."""

    metadata = {"render_modes": []}

    def __init__(self, features, prices, window: int = DEFAULT_WINDOW,
                 txn_cost_rate: float = DEFAULT_TXN_COST_RATE,
                 drawdown_penalty: float = DEFAULT_DRAWDOWN_PENALTY,
                 long_only: bool = False, episode_boundaries=None):
        super().__init__()
        self.features = [list(map(float, row)) for row in features]
        self.prices = [float(p) for p in prices]
        if len(self.features) != len(self.prices):
            raise ValueError("features and prices must have equal length")
        if window < 1:
            raise ValueError("window must be >= 1")
        if len(self.features) < window + 1:
            raise ValueError(
                f"need at least window+1 ({window + 1}) steps, got "
                f"{len(self.features)}")
        self.window = window
        self.txn_cost_rate = float(txn_cost_rate)
        self.drawdown_penalty = float(drawdown_penalty)
        self.long_only = bool(long_only)
        self._boundaries = set(int(b) for b in (episode_boundaries or []))

        self._feature_dim = len(self.features[0])
        self.obs_dim = self.window * self._feature_dim + 3  # + position one-hot
        self.observation_space = spaces.Box(
            low=-np.inf, high=np.inf, shape=(self.obs_dim,), dtype=np.float32)
        self.action_space = spaces.Discrete(3)

        self._t = 0
        self._position = 0
        self._equity = 0.0
        self._peak = 0.0

    # -- gym API ------------------------------------------------------------- #

    def reset(self, *, seed=None, options=None):
        super().reset(seed=seed)
        self._t = self.window - 1          # last bar of the initial window
        self._position = 0
        self._equity = 0.0
        self._peak = 0.0
        return self._obs(), {}

    def step(self, action):
        target = _ACTION_TO_POSITION[int(action)]
        if self.long_only and target < 0:
            target = 0                     # equities: short clamped to flat

        nxt = self._t + 1
        # Zero the return across a symbol boundary (no cross-instrument PnL).
        if nxt in self._boundaries or self.prices[self._t] == 0.0:
            market_ret = 0.0
        else:
            market_ret = self.prices[nxt] / self.prices[self._t] - 1.0

        realized = target * market_ret
        txn_cost = self.txn_cost_rate * abs(target - self._position)  # MANDATORY
        self._equity += realized
        self._peak = max(self._peak, self._equity)
        drawdown = max(0.0, self._peak - self._equity)
        reward = realized - txn_cost - self.drawdown_penalty * drawdown

        self._position = target
        self._t = nxt
        terminated = self._t >= len(self.features) - 1
        info = {"equity": self._equity, "drawdown": drawdown,
                "position": self._position, "txn_cost": txn_cost}
        return self._obs(), float(reward), terminated, False, info

    # -- helpers ------------------------------------------------------------- #

    def _position_one_hot(self):
        return {0: (1.0, 0.0, 0.0), 1: (0.0, 1.0, 0.0),
                -1: (0.0, 0.0, 1.0)}[self._position]

    def _obs(self):
        lo = self._t - self.window + 1
        rows = self.features[lo: self._t + 1]
        flat = [v for row in rows for v in row]
        flat.extend(self._position_one_hot())
        return np.asarray(flat, dtype=np.float32)
