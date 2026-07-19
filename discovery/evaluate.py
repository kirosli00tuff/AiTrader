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
verdict on their own. That mirrors the ensemble posture in CONTEXT.md: advisory influence
is bounded by the ensemble weights and by the +/- 0.10 adjustment cap here,
and no advisory layer may be a sole controller.

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
                  conviction_floor: float = 0.60,
                  min_directional: int = 1) -> dict:
    """Fuse the three advisory levels into a buy / sell / avoid verdict.

    Pure: takes already-scored layer outputs, so it is testable without any
    provider. ``council`` is a ConsensusResult-like object (bias, confidence,
    edge, verdict, agreement_count, per_model, directional_count, abstentions).

    Holds abstain (2026-07-18): ``council.confidence`` is the conviction among
    DIRECTIONAL voters, and ``min_directional`` is the minimum number of
    directional votes for a non-avoid verdict. At 1 (deliberately permissive,
    this evaluation period) a single convinced provider with two abstentions
    can act. The conviction_floor still applies to that conviction, so a lone
    unconvinced voter never passes on count alone.
    """
    council_bias = _safe_float(getattr(council, "bias", 0.0))
    council_conf = _clamp(_safe_float(getattr(council, "confidence", 0.0)), 0.0, 1.0)
    council_edge = _safe_float(getattr(council, "edge", 0.0))
    agreement = int(_safe_float(getattr(council, "agreement_count", 0)))
    directional_count = int(_safe_float(getattr(council, "directional_count", 0)))
    abstentions = int(_safe_float(getattr(council, "abstentions", 0)))

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
    # has a real direction, enough DIRECTIONAL voters, AND conviction (among
    # those voters) clears the floor. An all-abstain council is flat at
    # conviction 0.0 and lands here regardless of how confident the holds were.
    if (direction == "flat" or conviction < conviction_floor
            or directional_count < max(1, int(min_directional))):
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
        f"{council_bias:.2f}, conviction {council_conf:.2f} among "
        f"{directional_count} directional voter(s), {abstentions} abstained, "
        f"agreement {agreement}. Advisory dnn {dnn_bias:+.2f}, whale "
        f"{whale_bias:+.2f} -> conviction {conviction:.2f} ({adj:+.3f}). "
        + "; ".join(parts)
    )[:1000]

    return {
        "symbol": symbol,
        "verdict": verdict,
        "direction": direction,
        "conviction": round(conviction, 4),
        "edge": round(council_edge, 4),
        "agreement": agreement,
        "directional_count": directional_count,
        "abstentions": abstentions,
        "size_pct": size_pct,
        "horizon": horizon,
        "rationale": rationale,
        "council_confidence": round(council_conf, 4),
        "dnn_bias": round(dnn_bias, 4),
        "whale_bias": round(whale_bias, 4),
        "advisory_adjustment": round(adj, 4),
        # How many council providers were actually scored. 0 means the council
        # short-circuited (gate decline, risk pre-check, market-hours skip) and
        # no provider was contacted, which the funnel's budget counter reads as
        # zero spend. A ConsensusResult always carries per_model: scored
        # verdicts on a real run, [] on a short-circuit.
        "provider_calls": len(getattr(council, "per_model", None) or []),
    }


def market_state_from(snapshot: dict) -> dict:
    """The market signals llm_consensus.providers.build_user_prompt reads.

    THE KEY NAMES ARE THE CONTRACT. build_user_prompt renders exactly symbol,
    venue, price, ret_5, imbalance, catalyst, volatility, and defaults anything
    absent to 0.0. Stage C used to pass only symbol, price, category, mode, and
    horizon, so the council was asked to judge an instrument whose return,
    volatility, catalyst, and order-book imbalance were all zero. It answered
    "avoid" with conviction 0.0 every time, which was the only honest reading of
    that payload, at a full council call per survivor. The Stage-A snapshot held
    the real numbers the whole time; they were dropped on the way in.

    ret_5 is a fraction: Finnhub's change_pct is a percent, so it is scaled.
    imbalance stays absent because the free tier serves no order book, and an
    invented number would be worse than a missing one.
    """
    def _f(key: str) -> float:
        try:
            return float(snapshot.get(key) or 0.0)
        except (TypeError, ValueError):
            return 0.0

    price = _f("price")
    high, low = _f("high"), _f("low")
    out = {
        "price": price,
        "ret_5": _f("change_pct") / 100.0,
        "volatility": round(((high - low) / price) if price > 0 and high > low
                            else 0.0, 6),
    }
    if snapshot.get("sentiment_score") is not None:
        out["catalyst"] = _f("sentiment_score")
    return out


def four_level_evaluator(*, price_for=None, category_for=None,
                         snapshot_for=None, horizon: str = "short_term",
                         cfg_path: str | None = None, providers=None):
    """Build the Stage-C evaluator callable the funnel invokes per survivor.

    Returns callable(symbol) -> verdict dict. Imports the layer modules lazily so
    importing the funnel never drags in the ML stack, and so a missing optional
    dependency degrades one layer instead of breaking discovery.

    ``snapshot_for`` maps a symbol to its Stage-A market snapshot, so the council
    judges the instrument's actual movement. Without it the council sees a price
    and nothing else. Optional so existing callers keep working, but the funnel
    always supplies it: a council call against a blank snapshot is money spent to
    be told nothing.
    """
    from llm_consensus.config_access import (council_min_confidence,
                                             min_directional_votes)

    def _evaluate(symbol: str) -> dict:
        price = float(price_for(symbol)) if price_for else 0.0
        category = category_for(symbol) if category_for else "equity"
        state = {
            "symbol": symbol,
            "venue": "alpaca",
            "price": price,
            "category": category,
            "mode": "discovery",
            "horizon": horizon,
        }
        if snapshot_for:
            # Overlay the real signals, then restore price: the snapshot and
            # price_for agree, and price_for stays the one authority for it.
            state.update(market_state_from(snapshot_for(symbol) or {}))
            state["price"] = price

        # Level 2: the council. STAGE B ALREADY GATED THIS SYMBOL, so consensus
        # must not gate it again.
        #
        # It used to. consensus() runs the trading base-check gate by default,
        # and that gate renders an order book and a news catalyst the free
        # pre-screen cannot supply, defaulting both to 0.0. It therefore skipped
        # every discovery survivor, and consensus returned a flat verdict with
        # confidence 0.0 WITHOUT calling a single provider. So Stage C recorded 5
        # "council calls" and 5 avoid verdicts per pass while the council never
        # actually ran: the funnel could not surface a candidate in any market.
        #
        # Passing an always-proceed gate here is not a loosened cost control. It
        # restores the funnel's own design, where each stage screens ONCE and
        # narrows: Stage A ranks for free, Stage B is the cheap gate, Stage C is
        # the paid council on what survived. Spend stays bounded by
        # max_survivors, max_council_calls_per_pass, and the separate daily
        # discovery budget, none of which changed.
        from llm_consensus import consensus as _consensus
        from llm_consensus.gate import AlwaysProceedGate
        council = _consensus(state, providers=providers, cfg_path=cfg_path,
                             gate=AlwaysProceedGate())

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
                             conviction_floor=council_min_confidence(cfg_path),
                             min_directional=min_directional_votes(cfg_path))

    return _evaluate
