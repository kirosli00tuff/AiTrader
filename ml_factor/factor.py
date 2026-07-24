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

from .features import FEATURE_NAMES, features_at, serve_window
from .model import DnnModel

_MODELS_DIR = os.path.join(os.path.dirname(__file__), "models")
_CHAMPION_PATH = os.path.join(_MODELS_DIR, "champion.npz")
_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

_DEFAULT_SCALE_CAP = 0.5  # clamp on the dnn_position_scale_hint OUTPUT (advisory; nothing sizes on it)

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
    """Return the champion model, training + persisting a tiny one if absent.

    Self-heal, narrow by design: a champion.npz that predates the bars-v2
    signature AND is the known synthetic bootstrap (dnn-0.x) is retrained and
    replaced, because the bootstrap is a deterministic regenerable stand-in.
    Any OTHER unsigned artifact is left on disk untouched: score_state refuses
    it closed at serve time rather than destroying a model we cannot rebuild.
    """
    global _cached
    if _cached is not None:
        return _cached
    os.makedirs(_MODELS_DIR, exist_ok=True)
    if os.path.exists(_CHAMPION_PATH):
        model = DnnModel.load(_CHAMPION_PATH)
        if (not model.feature_names) and model.model_id.startswith("dnn-0"):
            model = DnnModel.train_synthetic(model_id=model.model_id)
            model.save(_CHAMPION_PATH)
        _cached = model
    else:
        _cached = DnnModel.train_synthetic(model_id="dnn-0.1.0")
        _cached.save(_CHAMPION_PATH)
    return _cached


def artifact_loadable(path: str) -> tuple[bool, str]:
    """Whether an artifact exists, loads, and carries the canonical signature
    plus its normalizer. The promotion path refuses a challenger that fails
    this: a metadata-only promotion must be impossible."""
    if not path or not os.path.exists(path):
        return False, f"no artifact on disk at '{path or '(none)'}'"
    try:
        model = DnnModel.load(path)
    except Exception as e:  # noqa: BLE001 — an unloadable artifact refuses
        return False, f"artifact failed to load ({type(e).__name__})"
    ok, why = model.signature_matches(list(FEATURE_NAMES))
    if not ok:
        return False, why
    return True, f"artifact {model.model_id} loadable, signature ok"


def install_champion_artifact(path: str) -> tuple[bool, str]:
    """Install a verified challenger artifact as the serving champion.

    Called by the audited promotion endpoint AFTER the registry promote, so
    the registry champion and the serving artifact agree, which is exactly
    what bench_state's artifact-match rule requires to unbench. Refuses an
    unloadable artifact rather than replacing a working champion with one.
    """
    global _cached, _bench_cache
    ok, why = artifact_loadable(path)
    if not ok:
        return False, why
    import shutil
    os.makedirs(_MODELS_DIR, exist_ok=True)
    shutil.copy2(path, _CHAMPION_PATH)
    _cached = None       # next score serves the new champion
    _bench_cache = None  # re-evaluate the bench against the new registry state
    return True, "installed"


def _unavailable(model_id: str, reason: str) -> dict:
    """Full-shape zero response for a state that cannot be scored honestly.

    Consistent with the bench behavior: the composed aliases are zero, the
    payload SAYS why, and nothing is invented. This replaces the old silent
    constant defaults: a symbol without real bars is unavailable, never scored
    on inputs the model would read as signal.
    """
    benched, bench_detail = bench_state()
    return {
        "dnn_action_bias": 0.0, "dnn_confidence": 0.0,
        "dnn_expected_edge": 0.0, "dnn_regime_label": "unavailable",
        "dnn_risk_flag": 0, "dnn_position_scale_hint": 0.0,
        "model_id": model_id, "available": False,
        "unavailable_reason": reason,
        "benched": benched,
        **({"benched_reason": bench_detail} if benched else {}),
        "bias": 0.0, "confidence": 0.0, "edge": 0.0,
        # ABSENT, not uncertain: an unavailable factor did not participate, so
        # the engine drops it from the confidence denominator rather than
        # averaging in a confident zero.
        "participating": False,
    }


def score_state(state: dict, scale_cap: float = _DEFAULT_SCALE_CAP) -> dict:
    """Score a market state -> advisory DNN outputs (sizing hint capped).

    The position scale hint is hard-capped here so the DNN can never request a
    size beyond its advisory cap; Layer-1 risk still bounds everything further.

    Serving builds features through THE canonical pipeline (features_at over
    the symbol's real bars), the same builder training uses, and refuses
    closed when it cannot: a signature mismatch, a missing symbol, or a symbol
    without enough real bars returns a flagged zero response instead of
    scoring invented inputs.
    """
    model = load_champion()
    sig_ok, sig_why = model.signature_matches(list(FEATURE_NAMES))
    if not sig_ok:
        return _unavailable(model.model_id, f"refused to serve: {sig_why}")
    symbol = str(state.get("symbol", "") or "")
    if not symbol:
        return _unavailable(model.model_id, "no symbol in state")
    bars, reason = serve_window(_default_db_path(), symbol)
    if bars is None:
        return _unavailable(model.model_id, reason)
    out = model.forward(features_at(bars, len(bars) - 1))
    out["available"] = True
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
    # ABSENT vs UNCERTAIN (2026-07-23): participation is the wire signal the
    # engine keys the denominator exclusion off. A benched factor did NOT
    # participate (its zeros are structural); a serving factor participates
    # even when its confidence is legitimately low.
    out["participating"] = not benched
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
         "price": 100}
    print(json.dumps(score_state(s), indent=2))
