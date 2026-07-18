"""DNN/RL advisory factor serving entry point.

Loads the champion model (training + saving a tiny one on first use so the demo
always has a real model), scores a market state, and applies the advisory
sizing cap. Output fields match DNN_ADVISORY_DESIGN.md exactly.
"""
from __future__ import annotations

import json
import os
import sqlite3
import time

from .features import build_features
from .model import DnnModel

_MODELS_DIR = os.path.join(os.path.dirname(__file__), "models")
_CHAMPION_PATH = os.path.join(_MODELS_DIR, "champion.npz")
_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

_DEFAULT_SCALE_CAP = 0.5  # sizing.dnn_position_scale_cap

_cached: DnnModel | None = None

# Bench-state cache (2026-07-18). Re-read every _BENCH_TTL_SECONDS so a
# promotion through the audited registry endpoint unbenches the factor without
# a bridge restart, without a registry read on every score call.
_BENCH_TTL_SECONDS = 30.0
_bench_cache: tuple[float, bool, str] | None = None


def _default_db_path() -> str:
    """MAL_DB_PATH, else the repo-root DB. Repo-anchored, never cwd-relative:
    the cwd class of bug is already on record (adaptive/run.py Open Flag)."""
    return os.environ.get("MAL_DB_PATH") or os.path.join(_REPO_ROOT,
                                                         "market_ai_lab.db")


def champion_is_real_trained(db_path: str | None = None) -> tuple[bool, str]:
    """Whether the SERVING champion trained on real fills. (ok, detail).

    Real requires ALL of: the model registry has a current champion row, its
    provenance is "real-data", and its model_id matches the artifact actually
    being served. Anything else (no registry, no row, synthetic provenance, an
    id mismatch, an unreadable DB) reads NOT real, which benches the factor.
    Same no-default-to-real posture as bar provenance, and the same graduation
    discipline as RL: an advisory trained only on synthetic labels must not
    move a verdict. Promotion criteria are unchanged; this reads their result.
    """
    serving_id = load_champion().model_id
    db = db_path or _default_db_path()
    try:
        conn = sqlite3.connect(f"file:{db}?mode=ro", uri=True, timeout=2.0)
        try:
            row = conn.execute(
                "SELECT model_id, metrics_json FROM model_registry"
                " WHERE role='champion' ORDER BY id DESC LIMIT 1").fetchone()
        finally:
            conn.close()
    except Exception:  # noqa: BLE001 — unreadable registry must bench, not raise
        return False, f"benched: registry unreadable, serving {serving_id}"
    if not row:
        return False, (f"benched pending real training: no champion in the "
                       f"registry, serving {serving_id} (synthetic)")
    reg_id = str(row[0] or "")
    try:
        provenance = str((json.loads(row[1] or "{}") or {}).get(
            "provenance", ""))
    except Exception:  # noqa: BLE001
        provenance = ""
    if provenance != "real-data":
        return False, (f"benched pending real training: champion {reg_id} "
                       f"provenance '{provenance or 'unknown'}'")
    if reg_id != serving_id:
        return False, (f"benched: registry champion {reg_id} does not match "
                       f"serving artifact {serving_id}")
    return True, f"champion {reg_id} real-data"


def bench_state(db_path: str | None = None) -> tuple[bool, str]:
    """(benched, detail), cached. benched means the factor contributes ZERO
    bias, confidence, and edge. Distinct from operator-disabled: the layer
    toggle is untouched and the raw model outputs stay visible."""
    global _bench_cache
    if db_path is not None:  # explicit path (tests) bypasses the cache
        real, detail = champion_is_real_trained(db_path)
        return (not real), detail
    now = time.time()
    if _bench_cache and now - _bench_cache[0] < _BENCH_TTL_SECONDS:
        return _bench_cache[1], _bench_cache[2]
    real, detail = champion_is_real_trained(None)
    _bench_cache = (now, not real, detail)
    return _bench_cache[1], _bench_cache[2]


def load_champion() -> DnnModel:
    """Return the champion model, training + persisting a tiny one if absent."""
    global _cached
    if _cached is not None:
        return _cached
    os.makedirs(_MODELS_DIR, exist_ok=True)
    if os.path.exists(_CHAMPION_PATH):
        _cached = DnnModel.load(_CHAMPION_PATH)
    else:
        _cached = DnnModel.train_synthetic(model_id="dnn-0.1.0")
        _cached.save(_CHAMPION_PATH)
    return _cached


def score_state(state: dict, scale_cap: float = _DEFAULT_SCALE_CAP) -> dict:
    """Score a market state -> advisory DNN outputs (sizing hint capped).

    The position scale hint is hard-capped here so the DNN can never request a
    size beyond its advisory cap; Layer-1 risk still bounds everything further.
    """
    model = load_champion()
    out = model.forward(build_features(state))
    out["dnn_position_scale_hint"] = round(
        min(out["dnn_position_scale_hint"], scale_cap), 4
    )
    out["model_id"] = model.model_id
    # Bench gate (2026-07-18): an advisory trained only on synthetic labels
    # must not move a verdict. The 17-of-17 negative reads were the synthetic
    # champion evaluated out of distribution (see RETURN.md): a constant that
    # cast the deciding vote against candidates it knew nothing about. While
    # benched, the raw dnn_* outputs stay visible and logged, and the ALIASES
    # every consumer composes from (bias, confidence, edge) are zero. When a
    # real-data champion is promoted, bench_state flips within its TTL and the
    # factor contributes normally. Distinct from operator-disabled: the layer
    # toggle is untouched.
    benched, detail = bench_state()
    out["benched"] = benched
    if benched:
        out["benched_reason"] = detail
        out["bias"] = 0.0
        out["confidence"] = 0.0
        out["edge"] = 0.0
    else:
        # Bridge-compatible aliases consumed by the C++ engine's generic reader.
        out["bias"] = out["dnn_action_bias"]
        out["confidence"] = out["dnn_confidence"]
        out["edge"] = out["dnn_expected_edge"]
    return out


if __name__ == "__main__":
    import json

    s = {"ret_5": 0.03, "volatility": 0.2, "imbalance": 0.4, "catalyst": 0.5,
         "price": 100, "spread": 0.1}
    print(json.dumps(score_state(s), indent=2))
