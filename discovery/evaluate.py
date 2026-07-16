"""Stage C: the four-level evaluation of a discovery survivor.

Reuses the EXISTING layers rather than reimplementing them:
  Level 2  LLM council      llm_consensus.consensus (the Haiku gate screens inside)
  Level 3  DNN advisory     ml_factor.score_state
  Level 4  whale            whale_signal.whale_signal_for

Level 1 is deliberately absent here. The deterministic RiskGate is the C++
engine's final authority and judges any resulting order at execution time. A
discovery verdict is a RECOMMENDATION, never an execution: nothing in this module
can open a position, size past a cap, or weaken a limit.

The council leads. The DNN and whale layers are ADVISORY: they confirm or temper
the council's conviction within a bounded adjustment, and can never flip a
verdict on their own. That mirrors the ensemble posture in CONTEXT.md, where the
whale layer is capped at 0.35 and the DNN at 0.5 and neither may be a sole
controller.

The same machinery serves BOTH sleeves. The only difference is the horizon and
the prompt framing: short-term-trade mode for quant_core, long-term-hold mode for
research_satellite.
"""
from __future__ import annotations

import logging

log = logging.getLogger("discovery.evaluate")

# How far the advisory layers may move the council's conviction, in total. Small
# on purpose: advisory means advisory. A confirming DNN and whale lift conviction
# by at most this, a contradicting pair cut it by at most this.
_ADVISORY_ADJUST_MAX = 0.10

# Direction thresholds on the council bias.
_LONG_BIAS = 0.10
_SHORT_BIAS = -0.10


def _clamp(x: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, x))


def _safe_float(v, default: float = 0.0) -> float:
    try:
        return float(v)
    except (TypeError, ValueError):
        return default


def advisory_adjustment(council_bias: float, dnn_bias: float,
                        whale_bias: float) -> float:
    """How much the advisory layers move conviction, bounded and signed.

    Agreement with the council's direction lifts conviction, disagreement cuts
    it. The result is clamped to +/- _ADVISORY_ADJUST_MAX, so no advisory layer
    can ever be decisive. A flat council bias means there is no direction to
    agree with, so the adjustment is zero.
    """
    if abs(council_bias) < 1e-9:
        return 0.0
    direction = 1.0 if council_bias > 0 else -1.0
    # Each advisory layer contributes half the budget, scaled by how strongly it
    # agrees (or disagrees) with the council's direction.
    dnn_agree = _clamp(dnn_bias * direction, -1.0, 1.0)
    whale_agree = _clamp(whale_bias * direction, -1.0, 1.0)
    adj = (dnn_agree + whale_agree) / 2.0 * _ADVISORY_ADJUST_MAX
    return _clamp(adj, -_ADVISORY_ADJUST_MAX, _ADVISORY_ADJUST_MAX)


def build_verdict(*, symbol: str, council, dnn: dict, whale: dict,
                  horizon: str = "short_term",
                  conviction_floor: float = 0.60) -> dict:
    """Fuse the three advisory levels into a buy / sell / avoid verdict.

    Pure: takes already-scored layer outputs, so it is testable without any
    provider. ``council`` is a ConsensusResult-like object (bias, confidence,
    edge, verdict, agreement_count, per_model).
    """
    council_bias = _safe_float(getattr(council, "bias", 0.0))
    council_conf = _clamp(_safe_float(getattr(council, "confidence", 0.0)), 0.0, 1.0)
    council_edge = _safe_float(getattr(council, "edge", 0.0))
    agreement = int(_safe_float(getattr(council, "agreement_count", 0)))

    dnn_bias = _clamp(_safe_float((dnn or {}).get("bias")), -1.0, 1.0)
    whale_bias = _clamp(
        _safe_float((whale or {}).get("whale_bias", (whale or {}).get("bias"))),
        -1.0, 1.0)

    adj = advisory_adjustment(council_bias, dnn_bias, whale_bias)
    conviction = _clamp(council_conf + adj, 0.0, 1.0)

    if council_bias >= _LONG_BIAS:
        direction = "long"
    elif council_bias <= _SHORT_BIAS:
        direction = "short"
    else:
        direction = "flat"

    # avoid is the default. A verdict becomes actionable only when the council
    # has a real direction AND conviction clears the floor.
    if direction == "flat" or conviction < conviction_floor:
        verdict = "avoid"
    elif direction == "long":
        verdict = "buy"
    else:
        verdict = "sell"

    # Suggested size as a fraction of the sleeve's room, scaled by conviction.
    # ADVISORY ONLY: the engine applies the hard sleeve cap and the RiskGate,
    # both of which can only reduce this, never raise it.
    size_pct = round(conviction * 0.5, 4) if verdict != "avoid" else 0.0

    parts = []
    for v in (getattr(council, "per_model", None) or []):
        parts.append(f"{getattr(v, 'model', 'model')}={getattr(v, 'verdict', '')}")
    rationale = (
        f"Council {getattr(council, 'verdict', '?')} on {symbol}: bias "
        f"{council_bias:.2f}, confidence {council_conf:.2f}, agreement "
        f"{agreement}. Advisory dnn {dnn_bias:+.2f}, whale {whale_bias:+.2f} "
        f"-> conviction {conviction:.2f} ({adj:+.3f}). " + "; ".join(parts)
    )[:1000]

    return {
        "symbol": symbol,
        "verdict": verdict,
        "direction": direction,
        "conviction": round(conviction, 4),
        "edge": round(council_edge, 4),
        "agreement": agreement,
        "size_pct": size_pct,
        "horizon": horizon,
        "rationale": rationale,
        "council_confidence": round(council_conf, 4),
        "dnn_bias": round(dnn_bias, 4),
        "whale_bias": round(whale_bias, 4),
        "advisory_adjustment": round(adj, 4),
    }


def four_level_evaluator(*, price_for=None, category_for=None,
                         horizon: str = "short_term",
                         cfg_path: str | None = None, providers=None):
    """Build the Stage-C evaluator callable the funnel invokes per survivor.

    Returns callable(symbol) -> verdict dict. Imports the layer modules lazily so
    importing the funnel never drags in the ML stack, and so a missing optional
    dependency degrades one layer instead of breaking discovery.
    """
    from llm_consensus.config_access import council_min_confidence

    def _evaluate(symbol: str) -> dict:
        price = float(price_for(symbol)) if price_for else 0.0
        category = category_for(symbol) if category_for else "equity"
        state = {
            "symbol": symbol,
            "price": price,
            "category": category,
            "mode": "discovery",
            "horizon": horizon,
        }

        # Level 2: the council. The Haiku gate screens inside consensus, so a
        # weak survivor still cannot run up a full three-provider bill.
        from llm_consensus import consensus as _consensus
        council = _consensus(state, providers=providers, cfg_path=cfg_path)

        # Level 3: DNN advisory. A failure degrades to neutral, never fatal.
        dnn: dict = {}
        try:
            from ml_factor import score_state
            dnn = score_state(state) or {}
        except Exception:  # noqa: BLE001
            log.debug("discovery: dnn advisory unavailable for %s", symbol)

        # Level 4: whale advisory. Same posture.
        whale: dict = {}
        try:
            from whale_signal import whale_signal_for
            sig, _ = whale_signal_for(symbol, market_bias=float(council.bias))
            whale = sig.to_dict() if hasattr(sig, "to_dict") else {}
        except Exception:  # noqa: BLE001
            log.debug("discovery: whale advisory unavailable for %s", symbol)

        return build_verdict(symbol=symbol, council=council, dnn=dnn,
                             whale=whale, horizon=horizon,
                             conviction_floor=council_min_confidence(cfg_path))

    return _evaluate
