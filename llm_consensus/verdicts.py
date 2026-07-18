"""Shared value types for the LLM council.

ADVISORY ONLY. These verdicts enter the C++ factor-combination engine as
weighted factors and can never bypass Layer-1 risk.
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass, field


def det_unit(seed: str) -> float:
    """Deterministic pseudo-random value in [0, 1) from a string seed."""
    h = int(hashlib.sha256(seed.encode()).hexdigest(), 16)
    return (h % 1_000_000) / 1_000_000.0


# Backwards-compatible private alias (older imports referenced ``_det_unit``).
_det_unit = det_unit


def clamp01(x: float) -> float:
    return max(0.0, min(1.0, x))


def bias_to_verdict(bias: float) -> str:
    if bias <= -0.6:
        return "strong_sell"
    if bias <= -0.2:
        return "sell"
    if bias < 0.2:
        return "hold"
    if bias < 0.6:
        return "buy"
    return "strong_buy"


# How a provider's directional call maps to a signed bias sign.
_DIRECTION_SIGN: dict[str, float] = {
    "long": 1.0, "buy": 1.0, "bull": 1.0, "bullish": 1.0,
    "short": -1.0, "sell": -1.0, "bear": -1.0, "bearish": -1.0,
    "flat": 0.0, "neutral": 0.0, "hold": 0.0,
}


def direction_sign(direction: str) -> float:
    return _DIRECTION_SIGN.get(str(direction).strip().lower(), 0.0)


@dataclass
class ModelVerdict:
    model: str            # ensemble slot name (e.g. "llm_primary")
    bias: float           # signed [-1, 1]
    confidence: float     # [0, 1]
    edge: float           # expected edge
    verdict: str          # bucketed label (strong_sell..strong_buy)
    rationale: str = ""   # one-line reason
    source: str = "mock"  # "real" | "mock" | "error" — provenance of this read
    model_id: str = ""    # concrete model id (e.g. "gpt-5.5"), from config


@dataclass
class ConsensusResult:
    bias: float
    confidence: float
    edge: float
    verdict: str
    agreement_count: int
    per_model: list[ModelVerdict] = field(default_factory=list)
    gate: dict | None = None  # base-check gate decision (None if no gate ran)
    # Abstention accounting (2026-07-18). A hold ABSTAINS from the directional
    # vote: bias, confidence, and edge are computed over directional voters
    # only, so a confident hold no longer dilutes a directional read toward
    # neutral. directional_count is how many providers expressed a direction,
    # abstentions how many held. per_model stays raw and complete, so nothing
    # is hidden by the aggregation.
    directional_count: int = 0
    abstentions: int = 0

    def to_dict(self) -> dict:
        d = {
            "bias": round(self.bias, 4),
            "confidence": round(self.confidence, 4),
            "edge": round(self.edge, 4),
            "verdict": self.verdict,
            "agreement_count": self.agreement_count,
            "directional_count": self.directional_count,
            "abstentions": self.abstentions,
            "per_model": [vars(m) for m in self.per_model],
        }
        if self.gate is not None:
            d["gate"] = self.gate
        return d


def verdict_from_payload(model: str, obj: dict, *, source: str = "real",
                         model_id: str = "") -> ModelVerdict:
    """Build a ModelVerdict from a parsed provider JSON payload.

    Providers return ``{direction, confidence, edge, rationale}``. We fold
    direction + confidence into a signed bias so the ensemble math (which weights
    by signed bias) is identical regardless of whether the read was real or mock.
    """
    direction = str(obj.get("direction", obj.get("verdict", "flat")))
    conf = clamp01(float(obj.get("confidence", 0.0)))
    edge = max(0.0, float(obj.get("edge", obj.get("edge_estimate", 0.0))))
    rationale = str(obj.get("rationale", obj.get("reason", "")))[:200]
    bias = max(-1.0, min(1.0, direction_sign(direction) * conf))
    return ModelVerdict(
        model=model,
        bias=round(bias, 4),
        confidence=round(conf, 4),
        edge=round(edge, 4),
        verdict=bias_to_verdict(bias),
        rationale=rationale,
        source=source,
        model_id=model_id,
    )


def flat_verdict(model: str, rationale: str, *, source: str = "error",
                 model_id: str = "") -> ModelVerdict:
    """Neutral/flat verdict used when a real call errors or can't be parsed."""
    return ModelVerdict(
        model=model,
        bias=0.0,
        confidence=0.0,
        edge=0.0,
        verdict=bias_to_verdict(0.0),
        rationale=rationale,
        source=source,
        model_id=model_id,
    )
