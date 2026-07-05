"""RL PPO trainer with a hard REAL-fill gate (Task 4).

Order of operations is deliberate and load-bearing:
  1. Read the real closed-fill count and the ``rl_min_real_fills`` gate.
  2. If below the gate, REFUSE with a clear message — BEFORE importing any heavy
     backend. There is NO synthetic-data training path for RL. None.
  3. Only past the gate do we build the REAL-bar env and lazily import
     stable-baselines3 / torch to train PPO.

The trained policy is walk-forward evaluated (rl_advisory/evaluate.py), saved as
a CHALLENGER artifact with provenance, and recorded in ``model_registry``.
Promotion to champion stays gated + manual (registry.meets_promotion_criteria);
nothing here auto-promotes.
"""
from __future__ import annotations

import os
import sqlite3

from ml_factor import registry

from .config import rl_min_real_fills
from .dataset import build_rl_dataset, count_real_fills

_MODELS_DIR = os.path.join(os.path.dirname(__file__), "models")
# Minimum real bar-steps (beyond the window) needed to build a usable env.
_MIN_TRAIN_STEPS = 64
_DEFAULT_WINDOW = 16


def train_rl_challenger(db_path: str, symbols: list[str],
                        cfg_path: str | None = None, timeframe: str = "5min",
                        total_timesteps: int = 10_000,
                        model_id: str = "ppo-real-0.1.0",
                        window: int = _DEFAULT_WINDOW,
                        long_only: bool = False) -> dict:
    """Train a gated RL challenger on REAL data, or refuse. Returns a status dict."""
    gate = rl_min_real_fills(cfg_path)
    n_fills = count_real_fills(db_path)
    result: dict = {
        "model_id": model_id,
        # "real-data" provenance (trained on real bars past the real-fill gate) so
        # the RL challenger competes via the SHARED promotion gate; the rl-ppo
        # marker distinguishes it from the supervised dnn_advisory challenger.
        "provenance": "real-data",
        "model_type": "rl-ppo",
        "n_real_fills": n_fills,
        "min_required": gate,
    }

    # --- GATE FIRST: refuse before importing any heavy backend. -------------
    if n_fills < gate:
        result["status"] = "insufficient_real_fills"
        result["note"] = (
            f"only {n_fills} real closed fills (< {gate}); RL trainer refuses. "
            "No synthetic-data training path exists for RL."
        )
        return result

    # Past the fill gate: assemble the REAL-bar dataset.
    ds = build_rl_dataset(db_path, symbols, timeframe)
    if ds.n_steps < window + _MIN_TRAIN_STEPS:
        result["status"] = "insufficient_real_bars"
        result["n_steps"] = ds.n_steps
        result["note"] = (
            f"fill gate met ({n_fills} >= {gate}) but only {ds.n_steps} real "
            f"bar-steps; need more persisted bars before RL training."
        )
        return result

    # Lazy-import the PPO backend ONLY now (torch/SB3 are optional deps pinned in
    # rl_advisory/requirements.txt; the env + service + gate work without them).
    try:
        from stable_baselines3 import PPO  # noqa: PLC0415
    except Exception as e:  # noqa: BLE001
        result["status"] = "backend_unavailable"
        result["note"] = (
            f"PPO backend (stable-baselines3/torch) not installed: {e}. "
            "Install rl_advisory/requirements.txt to train."
        )
        return result

    from .env import TradingEnv          # noqa: PLC0415
    from .evaluate import evaluate_policy  # noqa: PLC0415

    env = TradingEnv(ds.features, ds.prices, window=window, long_only=long_only,
                     episode_boundaries=ds.episode_boundaries)
    model = PPO("MlpPolicy", env, verbose=0)
    model.learn(total_timesteps=total_timesteps)

    eval_env = TradingEnv(ds.features, ds.prices, window=window,
                          long_only=long_only,
                          episode_boundaries=ds.episode_boundaries)
    metrics = evaluate_policy(
        eval_env, lambda obs: int(model.predict(obs, deterministic=True)[0]))

    os.makedirs(_MODELS_DIR, exist_ok=True)
    artifact = os.path.join(_MODELS_DIR, f"{model_id}.zip")
    model.save(artifact)

    # Record a GATED challenger with full provenance. Promotion is a separate,
    # explicit operator step (registry.meets_promotion_criteria); never here.
    conn = sqlite3.connect(db_path)
    try:
        registry.register(
            conn, model_id, "challenger",
            {"provenance": "real-data", "model_type": "rl-ppo",
             "n_samples": ds.n_steps,
             "validation_sharpe": metrics["validation_sharpe"],
             "max_drawdown": metrics["max_drawdown"],
             "n_real_fills": n_fills, "symbols": ds.symbols,
             "artifact": artifact},
            notes="RL PPO challenger; walk-forward evaluated; promotion gated")
    finally:
        conn.close()

    result.update(metrics)
    result["status"] = "challenger_recorded"
    result["n_samples"] = ds.n_steps
    result["artifact"] = artifact
    return result


if __name__ == "__main__":
    import argparse
    import json

    ap = argparse.ArgumentParser(
        description="Train + gate the real-data RL (PPO) advisory challenger.")
    ap.add_argument("--db", default="market_ai_lab.db")
    ap.add_argument("--symbols", default="BTC/USD,ETH/USD,SPY,QQQ")
    ap.add_argument("--timeframe", default="5min")
    ap.add_argument("--timesteps", type=int, default=10_000)
    args = ap.parse_args()
    out = train_rl_challenger(
        args.db, [s.strip() for s in args.symbols.split(",")],
        timeframe=args.timeframe, total_timesteps=args.timesteps)
    print(json.dumps(out, indent=2))
