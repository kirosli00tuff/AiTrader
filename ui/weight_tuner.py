"""Adaptive self-tuning of ADVISORY ensemble weights.

The bot continuously learns which advisors have recently been correct and nudges
the ensemble weights toward them to improve win rate. This is purely an advisory
re-blend: it is persisted through the exact same path manual edits use
(``db.save_weight_overrides`` -> ``weight_overrides.json`` + ``weight_changes``
audit) and can NEVER bypass or weaken the deterministic Layer-1 / Layer-2 safety
limits — identical to the existing manual override path.

Design:
  * ``compute_factor_accuracy`` derives a per-factor hit-rate over a trailing
    window of outcomes (``trades.outcome`` + ``model_outputs`` verdict agreement,
    and ``whale_signal_history`` agreement for the whale factor).
  * ``tune_weights`` is a PURE function: it nudges UNLOCKED factors toward the
    higher-accuracy ones with a responsive learning rate, keeps LOCKED factors
    frozen and excluded, enforces min/max floors, and preserves the total mass
    so the result still sums to 1 (locked values untouched).
  * ``run_auto_tune`` wires the two together and persists via
    ``save_weight_overrides(source="auto")`` only when the move is material.
"""
from __future__ import annotations

import db

# Responsive defaults (tunable). LEARNING_RATE is deliberately high so the panel
# values visibly track recent performance; floors stop any factor collapsing to
# zero or dominating entirely.
LEARNING_RATE = 0.25
W_MIN = 0.02
W_MAX = 0.60
WINDOW = 50
MIN_SAMPLES = 5          # need this many outcomes before trusting an accuracy
MIN_MATERIAL_DELTA = 0.005  # skip persistence/audit if no factor moved this much

_BULLISH = {"buy", "strong_buy"}
_BEARISH = {"sell", "strong_sell"}
# Non-whale factors recorded per-model in model_outputs.model.
_MODEL_FACTORS = ("llm_primary", "llm_secondary", "llm_tertiary",
                  "rule_based", "dnn_advisory")


# --- Pure tuner -------------------------------------------------------------

def _clamp(v: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, v))


def _apply_bounds(weights: dict[str, float], target_sum: float,
                  w_min: float, w_max: float) -> dict[str, float]:
    """Project weights into [w_min, w_max] while keeping the sum == target_sum.

    Clamps to the box, then iteratively spreads any residual (target minus
    current sum) equally across the factors that still have room in the needed
    direction. Converges in a handful of passes for the small factor counts here;
    if the box makes the target infeasible it returns the closest feasible point.
    """
    keys = list(weights)
    if not keys:
        return {}
    w = {k: _clamp(float(weights[k]), w_min, w_max) for k in keys}
    for _ in range(200):
        residual = target_sum - sum(w.values())
        if abs(residual) < 1e-12:
            break
        if residual > 0:
            adj = [k for k in keys if w[k] < w_max - 1e-12]
        else:
            adj = [k for k in keys if w[k] > w_min + 1e-12]
        if not adj:
            break  # infeasible within the box; return closest feasible point
        share = residual / len(adj)
        for k in adj:
            w[k] = _clamp(w[k] + share, w_min, w_max)
    return w


def tune_weights(current: dict[str, float],
                 accuracies: dict[str, float | None],
                 locks: dict[str, bool],
                 lr: float = LEARNING_RATE,
                 w_min: float = W_MIN,
                 w_max: float = W_MAX) -> dict[str, float]:
    """Return a new weight dict nudged toward higher-accuracy factors.

    * Locked factors keep their exact current value and are excluded from tuning.
    * Unlocked factors are scaled by ``1 + lr * (accuracy - mean_accuracy)`` so
      above-average advisors gain weight and below-average ones lose it.
    * Factors with no accuracy signal are left at their current value.
    * The unlocked pool's total mass is preserved, so locked values are untouched
      and the whole vector still sums to its original total (1.0 in practice).
    * Min/max floors are enforced on every unlocked factor.
    """
    factors = list(current.keys())
    result = {f: float(current[f]) for f in factors}
    locked = {f for f in factors if locks.get(f)}
    unlocked = [f for f in factors if f not in locked]
    pool = sum(current[f] for f in unlocked)
    if not unlocked or pool <= 0:
        return result

    scored = {f: accuracies.get(f) for f in unlocked
              if accuracies.get(f) is not None}
    mean_acc = (sum(scored.values()) / len(scored)) if scored else 0.0

    raw: dict[str, float] = {}
    for f in unlocked:
        acc = accuracies.get(f)
        if acc is None:
            raw[f] = current[f]
        else:
            raw[f] = max(1e-9, current[f] * (1.0 + lr * (acc - mean_acc)))

    total_raw = sum(raw.values())
    if total_raw <= 0:
        return result
    scaled = {f: raw[f] / total_raw * pool for f in unlocked}
    scaled = _apply_bounds(scaled, pool, w_min, w_max)
    result.update(scaled)
    return result


# --- Accuracy from recent outcomes ------------------------------------------

def _verdict_dir(verdict: str) -> int:
    v = str(verdict).lower()
    if v in _BULLISH:
        return 1
    if v in _BEARISH:
        return -1
    return 0


def compute_factor_accuracy(window: int = WINDOW) -> dict[str, float]:
    """Per-factor hit-rate over the trailing window, in [0, 1].

    A model factor is "correct" on a trade when its verdict direction agreed with
    the side actually taken and that trade won, OR it disagreed and the trade
    lost. The whale factor uses the stored agreement + trade outcome directly.
    Factors with fewer than ``MIN_SAMPLES`` aligned outcomes are omitted (None
    upstream), so they are left untuned rather than moved on noise.
    """
    acc: dict[str, float] = {}
    # --- model factors: align model_outputs to trades on identical ts ---
    try:
        for factor in _MODEL_FACTORS:
            df = db.query(
                "SELECT t.side AS side, t.outcome AS outcome, "
                "m.verdict AS verdict "
                "FROM trades t JOIN model_outputs m ON m.ts = t.ts "
                "WHERE m.model = ? AND t.outcome IN ('win','loss') "
                "ORDER BY t.id DESC LIMIT ?",
                (factor, int(window)),
            )
            if df.empty or len(df) < MIN_SAMPLES:
                continue
            correct = 0
            n = 0
            for _, row in df.iterrows():
                vdir = _verdict_dir(row["verdict"])
                if vdir == 0:
                    continue
                side_dir = 1 if str(row["side"]).lower() == "buy" else -1
                won = str(row["outcome"]).lower() == "win"
                agreed = (vdir == side_dir)
                if (agreed and won) or (not agreed and not won):
                    correct += 1
                n += 1
            if n >= MIN_SAMPLES:
                acc[factor] = correct / n
    except Exception:
        pass

    # --- whale factor: stored agreement vs eventual outcome ---
    try:
        wh = db.query(
            "SELECT agreed_with_trade, trade_outcome FROM whale_signal_history "
            "WHERE trade_outcome IN ('win','loss') AND agreed_with_trade IS NOT NULL "
            "ORDER BY id DESC LIMIT ?",
            (int(window),),
        )
        if not wh.empty and len(wh) >= MIN_SAMPLES:
            correct = 0
            for _, row in wh.iterrows():
                agreed = int(row["agreed_with_trade"]) == 1
                won = str(row["trade_outcome"]).lower() == "win"
                if (agreed and won) or (not agreed and not won):
                    correct += 1
            acc["whale_signal"] = correct / len(wh)
    except Exception:
        pass

    return acc


# --- Orchestration ----------------------------------------------------------

def run_auto_tune(window: int = WINDOW, lr: float = LEARNING_RATE,
                  w_min: float = W_MIN, w_max: float = W_MAX) -> dict:
    """Compute accuracies, nudge unlocked weights, and persist if material.

    Returns a small summary dict for the UI: the new effective weights, the
    per-factor accuracy used, lock state, and whether anything was persisted.
    Manual edits and locks always win (locked factors are never adjusted, and
    this writes through the same audited path as manual edits).
    """
    current = db.load_weight_overrides()
    locks = db.load_locks()
    accuracies = compute_factor_accuracy(window)
    new = tune_weights(current, accuracies, locks, lr=lr,
                       w_min=w_min, w_max=w_max)
    moved = max((abs(new[f] - current[f]) for f in current), default=0.0)
    persisted = False
    if moved >= MIN_MATERIAL_DELTA:
        # Same path manual edits use; source="auto" for the audit trail.
        db.save_weight_overrides(new, locks, source="auto")
        persisted = True
        effective = db.load_weight_overrides()
    else:
        effective = current
    return {
        "weights": effective,
        "accuracies": accuracies,
        "locks": locks,
        "persisted": persisted,
        "max_move": moved,
    }
