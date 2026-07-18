"""Real-data DNN advisory training + walk-forward validation (Task 5, Stage B).

Trains a small model on REAL persisted bars (see ml_factor/real_dataset.py) and
validates it **walk-forward** (expanding chronological windows — never a random
split, which would leak future information into the past). The result is recorded
as a *challenger* in `model_registry` with explicit provenance; it is NOT served
and NOT auto-promoted. Promotion to the live champion stays gated behind
`meets_promotion_criteria` + an explicit operator action (see registry.py).

Why a linear ridge model here (not the MLP): with only a few hundred real 5-min
samples, a regularised linear forward-return regressor is the honest capacity.
The advisory sizing cap (0.5) is unchanged and still applied at serve time by
ml_factor/factor.py. **True RL is deferred until we have >= 500 real closed
fills** — this supervised forward-return objective is the interim Stage B.
"""
from __future__ import annotations

import os
import sqlite3

import numpy as np

from . import registry
from .real_dataset import (N_REAL_FEATURES, REAL_FEATURE_NAMES,
                           build_real_dataset)

# Below this many real samples we refuse to train a real challenger — the DB
# does not yet hold enough history for an honest walk-forward estimate.
MIN_REAL_SAMPLES = 200
# Number of expanding walk-forward folds.
_N_FOLDS = 5
# Ridge regularisation strength.
_RIDGE_LAMBDA = 1.0


def _standardise(train: np.ndarray, other: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Standardise `other` using ONLY train-fold mean/std (no leakage)."""
    mu = train.mean(axis=0)
    sd = train.std(axis=0)
    sd[sd == 0.0] = 1.0
    return (train - mu) / sd, (other - mu) / sd


def _ridge_fit(X: np.ndarray, y: np.ndarray, lam: float) -> np.ndarray:
    """Closed-form ridge with an intercept column already appended to X."""
    d = X.shape[1]
    reg = lam * np.eye(d)
    reg[-1, -1] = 0.0  # do not penalise the intercept
    return np.linalg.solve(X.T @ X + reg, X.T @ y)


def _with_bias(X: np.ndarray) -> np.ndarray:
    return np.hstack([X, np.ones((X.shape[0], 1))])


def _max_drawdown(pnl_curve: np.ndarray) -> float:
    """Max peak-to-trough drawdown of a cumulative-PnL curve (>= 0)."""
    if pnl_curve.size == 0:
        return 0.0
    peak = np.maximum.accumulate(pnl_curve)
    return float(np.max(peak - pnl_curve))


def walk_forward_eval(X: list[list[float]], y: list[float],
                      n_folds: int = _N_FOLDS) -> dict:
    """Expanding-window walk-forward evaluation.

    For each fold, fit on all data strictly BEFORE the fold and predict the
    fold's forward returns. A directional position sign(pred) earns the realised
    forward return. Returns validation Sharpe (per-decision, not annualised) and
    max drawdown over the concatenated out-of-sample decisions.
    """
    Xa = np.asarray(X, dtype=float)
    ya = np.asarray(y, dtype=float)
    n = len(ya)
    # Fold boundaries: first fold is the initial train block, remaining folds are
    # the out-of-sample test blocks in chronological order.
    bounds = [int(round(n * k / (n_folds + 1))) for k in range(1, n_folds + 2)]
    oos_returns: list[float] = []
    for i in range(len(bounds) - 1):
        tr_end = bounds[i]
        te_end = bounds[i + 1]
        if tr_end < 10 or te_end <= tr_end:
            continue
        Xtr_raw, Xte_raw = Xa[:tr_end], Xa[tr_end:te_end]
        ytr, yte = ya[:tr_end], ya[tr_end:te_end]
        Xtr_s, Xte_s = _standardise(Xtr_raw, Xte_raw)
        w = _ridge_fit(_with_bias(Xtr_s), ytr, _RIDGE_LAMBDA)
        pred = _with_bias(Xte_s) @ w
        pos = np.sign(pred)
        oos_returns.extend((pos * yte).tolist())

    arr = np.asarray(oos_returns, dtype=float)
    if arr.size == 0 or arr.std() == 0.0:
        sharpe = 0.0
    else:
        sharpe = float(arr.mean() / arr.std())
    max_dd = _max_drawdown(np.cumsum(arr))
    return {
        "validation_sharpe": round(sharpe, 4),   # per-decision, not annualised
        "max_drawdown": round(max_dd, 6),
        "n_oos_decisions": int(arr.size),
        "mean_oos_return": round(float(arr.mean()) if arr.size else 0.0, 6),
    }


def train_real_challenger(db_path: str, symbols: list[str],
                          timeframe: str = "5min", horizon: int = 5,
                          model_id: str = "dnn-real-0.1.0") -> dict:
    """Build the real dataset, walk-forward validate, and register a challenger.

    Returns a status dict. If there are too few real samples, NO challenger is
    written — we report the shortfall instead of pretending to have learned.
    """
    ds = build_real_dataset(db_path, symbols, timeframe, horizon)
    result: dict = {
        "model_id": model_id,
        "provenance": "real-data",
        "n_samples": ds.n_samples,
        "n_closed_trades": ds.n_closed_trades,
        "feature_names": REAL_FEATURE_NAMES,
        "n_features": N_REAL_FEATURES,
        "horizon": horizon,
    }
    if ds.n_samples < MIN_REAL_SAMPLES:
        result["status"] = "insufficient_real_data"
        result["min_required"] = MIN_REAL_SAMPLES
        result["note"] = (
            f"only {ds.n_samples} real samples (< {MIN_REAL_SAMPLES}); "
            "synthetic champion remains; no real challenger recorded"
        )
        return result

    metrics = walk_forward_eval(ds.X, ds.y)
    result.update(metrics)
    result["status"] = "challenger_recorded"

    # Train the SERVABLE artifact (2026-07-18). A challenger used to be
    # registry metadata only, so a promotion flipped roles while serving kept
    # loading the old champion.npz. Now the challenger trains on the canonical
    # features through the same builder serving uses and saves an artifact
    # carrying its feature signature and fitted normalizer. Promotion refuses
    # a challenger without a loadable artifact (api_server.controls).
    from .model import DnnModel
    model = DnnModel.train_real_supervised(ds.X, ds.y, model_id=model_id)
    models_dir = os.path.join(os.path.dirname(__file__), "models")
    os.makedirs(models_dir, exist_ok=True)
    artifact_path = os.path.join(models_dir, f"challenger-{model_id}.npz")
    model.save(artifact_path)
    result["artifact_path"] = artifact_path

    # Record as a GATED challenger with full provenance. Promotion is a separate,
    # explicit step (registry.evaluate_and_maybe_promote with auto_promote=False).
    conn = sqlite3.connect(db_path)
    try:
        registry.register(
            conn, model_id, "challenger",
            {"provenance": "real-data", "n_samples": ds.n_samples,
             "validation_sharpe": metrics["validation_sharpe"],
             "max_drawdown": metrics["max_drawdown"],
             "horizon": horizon, "feature_set": REAL_FEATURE_NAMES,
             "artifact_path": artifact_path},
            notes="walk-forward validated on real bars; promotion gated",
        )
    finally:
        conn.close()
    return result


if __name__ == "__main__":
    import argparse
    import json

    ap = argparse.ArgumentParser(
        description="Train + walk-forward validate the real-data DNN challenger.")
    ap.add_argument("--db", default="market_ai_lab.db")
    ap.add_argument("--symbols", default="BTC/USD,ETH/USD,SPY,QQQ")
    ap.add_argument("--timeframe", default="5min")
    ap.add_argument("--horizon", type=int, default=5)
    args = ap.parse_args()
    out = train_real_challenger(
        args.db, [s.strip() for s in args.symbols.split(",")],
        args.timeframe, args.horizon)
    print(json.dumps(out, indent=2))
