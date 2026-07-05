"""RL walk-forward evaluation + champion/challenger gate (Task 4).

Evaluation matches the dnn_advisory pipeline: chronological EXPANDING windows
(never a random split, which would leak the future into the past). A separate
evaluation env runs a DETERMINISTIC policy, averaging 5-20 episodes per window.

The RL challenger competes against the SUPERVISED champion on validation Sharpe
plus a drawdown-no-worse rule. The comparison reuses the shared, gated
``ml_factor.registry.meets_promotion_criteria`` so RL promotion obeys the same
criteria as the supervised factor — and promotion still requires an explicit
operator action (nothing here auto-promotes).
"""
from __future__ import annotations

import numpy as np

from ml_factor import registry

# Match the dnn_advisory walk-forward fold count.
_N_FOLDS = 5
_MIN_EPISODES = 5
_MAX_EPISODES = 20


def walk_forward_windows(n_steps: int, n_folds: int = _N_FOLDS):
    """Expanding chronological (train_end, test_end) windows over n_steps."""
    bounds = [int(round(n_steps * k / (n_folds + 1))) for k in range(1, n_folds + 2)]
    windows = []
    for i in range(len(bounds) - 1):
        tr_end, te_end = bounds[i], bounds[i + 1]
        if tr_end < 1 or te_end <= tr_end:
            continue
        windows.append((tr_end, te_end))
    return windows


def evaluate_policy(env, policy, n_episodes: int = _MIN_EPISODES) -> dict:
    """Run a DETERMINISTIC policy over ``env`` for n_episodes; average metrics.

    ``policy`` is any callable ``obs -> action`` (e.g. a trained PPO's
    ``predict(obs, deterministic=True)``), so this is backend-agnostic and needs
    no torch. The env is deterministic, so episodes agree; we still average
    n_episodes (clamped to [5, 20]) to match the RL evaluation protocol.
    """
    n_episodes = max(_MIN_EPISODES, min(_MAX_EPISODES, int(n_episodes)))
    sharpes: list[float] = []
    drawdowns: list[float] = []
    for _ in range(n_episodes):
        obs, _info = env.reset()
        rewards: list[float] = []
        max_dd = 0.0
        done = False
        while not done:
            obs, r, terminated, truncated, info = env.step(policy(obs))
            rewards.append(r)
            max_dd = max(max_dd, float(info.get("drawdown", 0.0)))
            done = terminated or truncated
        arr = np.asarray(rewards, dtype=float)
        sharpe = float(arr.mean() / arr.std()) if arr.size and arr.std() > 0 else 0.0
        sharpes.append(sharpe)
        drawdowns.append(max_dd)
    return {
        "validation_sharpe": round(float(np.mean(sharpes)), 4),
        "max_drawdown": round(float(np.mean(drawdowns)), 6),
        "n_episodes": n_episodes,
    }


def challenger_beats_champion(champion_metrics: dict, challenger_metrics: dict,
                              min_real_samples: int = 200) -> tuple[bool, str]:
    """RL challenger vs supervised champion via the shared, gated criteria.

    Returns (ok, reason). Promotion still requires an explicit operator action.
    """
    return registry.meets_promotion_criteria(
        champion_metrics, challenger_metrics, min_real_samples)
