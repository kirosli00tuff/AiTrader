"""Deep-research thesis for the research_satellite sleeve.

Runs the LLM council on a research-framed candidate and returns a STRUCTURED
long-term thesis: direction, conviction, target horizon, and a written rationale.
The Haiku base-check gate screens the candidate inside ``consensus`` before the
full council runs, the same cost-control pattern the quant council uses, so a
low-value candidate never pays for the full council. This module only produces a
thesis; the C++ engine enforces the hard satellite cap, the conviction threshold,
and the RiskGate on any resulting order. It never logs a key value.
"""
from __future__ import annotations

from typing import Any

from llm_consensus import consensus
from llm_consensus.config_access import research_conviction_threshold


def research_thesis(payload: dict, providers: list | None = None,
                    cfg_path: str | None = None) -> dict:
    """Produce a structured research thesis for one candidate instrument.

    Reuses the council (gate-screened) and maps its consensus verdict to a
    long-term thesis. Never raises: a council failure degrades to a flat,
    zero-conviction thesis that the engine will not act on.
    """
    symbol = str(payload.get("symbol", "?"))
    # Frame the state for DEEP research: a longer horizon than the quick council.
    state: dict[str, Any] = dict(payload)
    state["mode"] = "deep_research"
    state.setdefault("horizon", "weeks_to_months")

    try:
        result = consensus(state, providers=providers, cfg_path=cfg_path)
    except Exception:
        return {"symbol": symbol, "direction": "flat", "conviction": 0.0,
                "horizon": "unknown", "rationale": "council unavailable",
                "verdict": "hold", "agreement_count": 0}

    bias = float(result.bias)
    if bias >= 0.1:
        direction = "long"
    elif bias <= -0.1:
        direction = "short"
    else:
        direction = "flat"
    conviction = max(0.0, min(1.0, float(result.confidence)))
    # A stronger directional bias implies a longer conviction horizon.
    horizon = "months" if abs(bias) >= 0.5 else "weeks"

    # Rationale from the per-model verdicts (bucketed labels + one-line reasons,
    # never a key value). Bounded length.
    parts = []
    for v in (result.per_model or []):
        label = getattr(v, "verdict", "")
        reason = getattr(v, "rationale", "") or ""
        model = getattr(v, "model", "model")
        parts.append(f"{model}={label}" + (f" ({reason})" if reason else ""))
    rationale = (
        f"Council {result.verdict} on {symbol}: bias {bias:.2f}, "
        f"edge {float(result.edge):.3f}, agreement {result.agreement_count}. "
        + "; ".join(parts)
    )[:1000]

    return {
        "symbol": symbol,
        "direction": direction,
        "conviction": round(conviction, 4),
        "horizon": horizon,
        "rationale": rationale,
        "verdict": result.verdict,
        "agreement_count": int(result.agreement_count),
        # Echo the conviction gate the engine will apply, for the GUI/tests.
        "conviction_threshold": research_conviction_threshold(cfg_path),
    }
