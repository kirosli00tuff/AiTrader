"""RL advisory serving entry point (Task 4).

Scores a market state into an advisory verdict for the /score/rl bridge
endpoint. Three cases, none of which ever raise (offline runs must not break):

  * RL disabled (default)         -> a labelled NEUTRAL "disabled" verdict; the
                                     factor is out of the ensemble.
  * RL enabled, NO model artifact -> a labelled deterministic MOCK verdict
                                     (source="mock") so the bridge still answers.
  * RL enabled, artifact present  -> the trained PPO policy scores the state
                                     (source="real"); torch/SB3 are imported
                                     lazily ONLY on this path.

Advisory only: the position-scale hint is hard-capped at RL_ADVISORY_CAP (0.5),
identical to dnn_advisory, and Layer-1 risk still bounds everything downstream.
"""
from __future__ import annotations

import hashlib
import os

from .config import RL_ADVISORY_CAP, rl_enabled, rl_min_real_fills

_MODELS_DIR = os.path.join(os.path.dirname(__file__), "models")
# stable-baselines3 saves policies as a .zip archive.
_CHAMPION_PATH = os.path.join(_MODELS_DIR, "ppo_champion.zip")


def _det_unit(seed: str) -> float:
    h = int(hashlib.sha256(seed.encode()).hexdigest(), 16)
    return (h % 1_000_000) / 1_000_000.0


def _bucket(bias: float) -> str:
    if bias <= -0.6:
        return "strong_sell"
    if bias <= -0.2:
        return "sell"
    if bias < 0.2:
        return "hold"
    if bias < 0.6:
        return "buy"
    return "strong_buy"


def _verdict(bias: float, confidence: float, edge: float, *, source: str,
             rationale: str, model_id: str = "") -> dict:
    """Standard advisory verdict with bridge-compatible {bias,confidence,edge}."""
    bias = max(-1.0, min(1.0, bias))
    confidence = max(0.0, min(1.0, confidence))
    edge = max(0.0, edge)
    hint = min(abs(bias) * confidence, RL_ADVISORY_CAP)  # advisory sizing hint
    return {
        "bias": round(bias, 4),
        "confidence": round(confidence, 4),
        "edge": round(edge, 4),
        "rl_position_scale_hint": round(hint, 4),
        "verdict": _bucket(bias),
        "source": source,
        "model_id": model_id,
        "rationale": rationale,
    }


def rl_gate_unmet(cfg_path: str | None = None) -> tuple[int, int] | None:
    """(fills, gate) when the real-fill gate is NOT met, else None.

    CLAUDE.md, a hard rule: "RL ships toggled off, trains only on real fills, and
    activates only past the rl_min_real_fills gate". That gate lived ONLY at the
    GUI write (api_server.set_rl refuses below it), so it was a property of one
    code path rather than of the system: a hand-edited config, or now a
    hand-edited controls.json, could set rl_enabled true under-gated and score_rl
    would serve a policy that was never entitled to run.

    So the gate is checked HERE, at the read, where it cannot be routed around.
    Counted with ml_factor.real_dataset.count_closed_trades, the canonical
    definition (STRATEGY fills only, so an adaptive exit or a rebalance trim
    cannot inflate a gate that exists to withhold RL until the policy itself has
    been exercised).

    Cost: this runs ONLY when rl_enabled is already true, which today it is not,
    so the disabled path stays one dict read with no DB touch and no numpy
    import. Fails CLOSED: if the count cannot be read, the gate reports unmet.
    """
    gate = rl_min_real_fills(cfg_path)
    try:
        import sqlite3
        from ml_factor.real_dataset import count_closed_trades
        db = os.environ.get("MAL_DB_PATH", "market_ai_lab.db")
        conn = sqlite3.connect(f"file:{db}?mode=ro", uri=True, timeout=2.0)
        try:
            fills = int(count_closed_trades(conn))
        finally:
            conn.close()
    except Exception:  # noqa: BLE001 — unprovable counts as zero, so it gates
        fills = 0
    # One comparison for both paths, so an unreadable count fails CLOSED without
    # special-casing it. A gate of 0 means no gate, and must stay ungated even
    # when the count cannot be read.
    return None if fills >= gate else (fills, gate)


def score_rl(state: dict, cfg_path: str | None = None) -> dict:
    """Advisory RL verdict for a market state. Never raises."""
    if not rl_enabled(cfg_path):
        # RL ships OFF: neutral + labelled, and out of the ensemble entirely.
        return _verdict(0.0, 0.0, 0.0, source="disabled",
                        rationale="RL disabled (rl_enabled=false): out of ensemble")

    # Enabled, but the hard rule outranks the flag. A toggle is a request; the
    # real-fill gate decides. Neutral and labelled exactly like disabled, so an
    # under-gated RL contributes nothing to the ensemble rather than a guess.
    unmet = rl_gate_unmet(cfg_path)
    if unmet is not None:
        fills, gate = unmet
        return _verdict(0.0, 0.0, 0.0, source="gated",
                        rationale=(f"RL gated: {fills} real strategy fills < "
                                   f"{gate} rl_min_real_fills: out of ensemble"))

    if not os.path.exists(_CHAMPION_PATH):
        # Enabled but no trained artifact yet -> deterministic labelled MOCK so
        # the bridge always answers. NO torch/SB3 import on this path.
        symbol = str(state.get("symbol", "?"))
        ret5 = float(state.get("ret_5", 0.0))
        bias = max(-1.0, min(1.0, ret5 * 20.0 + (_det_unit("rl" + symbol) - 0.5) * 0.2))
        conf = 0.2 + 0.3 * abs(bias)          # advisory: deliberately low
        edge = 0.01 * abs(bias)
        return _verdict(bias, conf, edge, source="mock",
                        rationale="MOCK (no RL model artifact): advisory placeholder")

    # Enabled AND a trained artifact exists: score with the real policy.
    return _score_with_policy(state)


def _score_with_policy(state: dict) -> dict:
    """Load the PPO policy (lazy torch/SB3) and score. Falls back to neutral on error."""
    try:
        from stable_baselines3 import PPO  # noqa: PLC0415
        model = PPO.load(_CHAMPION_PATH)
        # A live-serving observation builder is out of scope for the shipped-off
        # module; when wired, build the rolling window from recent bars here.
        # Until then, if the caller passes a prebuilt "obs" use it, else error.
        obs = state.get("obs")
        if obs is None:
            raise ValueError("no observation window supplied for live scoring")
        action, _ = model.predict(obs, deterministic=True)
        pos = {0: 0.0, 1: 1.0, 2: -1.0}.get(int(action), 0.0)
        return _verdict(pos, 0.5, 0.02, source="real",
                        rationale="RL policy (deterministic)",
                        model_id=os.path.basename(_CHAMPION_PATH))
    except Exception as e:  # noqa: BLE001 — never crash the bridge
        return _verdict(0.0, 0.0, 0.0, source="error",
                        rationale=f"RL scoring error, neutral: {e}")


def rl_ensemble_factor_names(base_factors, cfg_path: str | None = None) -> list[str]:
    """Ensemble factor list with ``rl_advisory`` appended ONLY when RL is enabled.

    When rl_enabled is false the RL factor stays out of the ensemble entirely —
    this mirrors the C++ engine's gather_factors behaviour and is the Python
    surface the test asserts against.
    """
    names = list(base_factors)
    if rl_enabled(cfg_path):
        names.append("rl_advisory")
    return names
