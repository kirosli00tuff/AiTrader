"""Shared value types for the LLM council.

ADVISORY ONLY. These verdicts enter the C++ factor-combination engine as
weighted factors and can never bypass Layer-1 risk.
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass, field


# Provenance values for ModelVerdict.source. "real" and "mock" are reads;
# these two are non-answers, and they are different non-answers.
ERROR_SOURCE = "error"          # the call was made and failed
EXHAUSTED_SOURCE = "exhausted"  # the account is out of quota or credit


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
    rationale: str = ""   # the model's written reasoning
    source: str = "mock"  # "real" | "mock" | "error" — provenance of this read
    model_id: str = ""    # concrete model id (e.g. "gpt-5.5"), from config
    # Long-term mode extras (target_view, horizon_weeks, invalidation).
    # Recorded and persisted as reasoning, never executed as levels.
    extra: dict = field(default_factory=dict)


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
    # A CONSIDERED HOLD ONLY (2026-07-25). This used to be
    # len(verdicts) - len(directional), which counted a provider that never
    # answered as one that read the evidence and held. Across the recorded
    # history 17 of 57 llm_tertiary rows were failed calls recorded as
    # abstentions, and council_eval 1 reads "2 directional, 1 abstained,
    # strong_buy" when the third provider errored.
    abstentions: int = 0
    # Providers whose call FAILED. Excluded from abstentions, excluded from
    # directional, and contributing nothing to bias, confidence, edge, or
    # agreement, exactly as before. This field changes what the record says,
    # never what the council decides.
    #
    # DISJOINT FROM `exhausted` (2026-07-27): a transient or permanent call
    # failure counts here, an account out of quota counts there, and
    # directional + abstentions + errors + exhausted equals the provider count.
    errors: int = 0
    # Providers not called, or failed, because the account is out of quota or
    # credit. A latching condition on the ACCOUNT rather than a per-call
    # failure, so a council running one-handed on a dry key is visible in the
    # record instead of being inferred from a log afterwards.
    exhausted: int = 0
    # Why no call was made (2026-07-25). Set only when the pre-call evidence
    # check refused: the providers were never contacted and no prompt was ever
    # rendered, so per_model is empty and the budget is charged nothing. None
    # on every round that actually ran, and on a gate decline, which is a
    # different event with a different reason.
    refusal: dict | None = None

    def to_dict(self) -> dict:
        d = {
            "bias": round(self.bias, 4),
            "confidence": round(self.confidence, 4),
            "edge": round(self.edge, 4),
            "verdict": self.verdict,
            "agreement_count": self.agreement_count,
            "directional_count": self.directional_count,
            "abstentions": self.abstentions,
            "errors": self.errors,
            "exhausted": self.exhausted,
            # How many providers actually answered. A two-handed round is now
            # visible without joining the per-provider rows.
            "responded_count": self.directional_count + self.abstentions,
            "per_model": [vars(m) for m in self.per_model],
        }
        if self.gate is not None:
            d["gate"] = self.gate
        if self.refusal is not None:
            d["refusal"] = self.refusal
        return d


def verdict_from_payload(model: str, obj: dict, *, source: str = "real",
                         model_id: str = "") -> ModelVerdict:
    """Build a ModelVerdict from a parsed provider JSON payload.

    Providers answer reasoning FIRST (the 2026-07-20 schema), then
    ``{direction, confidence, edge}``. Older shapes with ``rationale`` or
    ``reason`` still parse. Direction + confidence fold into a signed bias so
    the ensemble math is identical whether the read was real or mock. The
    long-term extras (target_view, horizon_weeks, invalidation) are carried on
    ``extra`` for the persisted record and are never executed as levels.
    """
    direction = str(obj.get("direction", obj.get("verdict", "flat")))
    conf = clamp01(float(obj.get("confidence", 0.0)))
    edge = max(0.0, float(obj.get("edge", obj.get("edge_estimate", 0.0))))
    rationale = str(obj.get("reasoning", obj.get("rationale",
                                                 obj.get("reason", ""))))[:500]
    extra = {k: obj[k] for k in ("target_view", "horizon_weeks", "invalidation")
             if k in obj}
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
        extra=extra,
    )


def flat_verdict(model: str, rationale: str, *, source: str = "error",
                 model_id: str = "", extra: dict | None = None) -> ModelVerdict:
    """Neutral/flat verdict used when a real call errors or can't be parsed.

    `source` is what separates this from a considered hold, everywhere it
    matters. The bias is 0.0 in both cases and always will be, because a
    provider that never answered has no direction to contribute, so no
    downstream count may key off the bias alone (2026-07-25).
    """
    return ModelVerdict(
        model=model,
        bias=0.0,
        confidence=0.0,
        edge=0.0,
        verdict=bias_to_verdict(0.0),
        rationale=rationale,
        source=source,
        model_id=model_id,
        extra=dict(extra or {}),
    )


def is_error(v: ModelVerdict) -> bool:
    """Whether this verdict is a NON-ANSWER rather than a considered read.

    One predicate, shared by the composer, the persister, and the API, so
    "errored" cannot come to mean three slightly different things in three
    places. A failed call and a hold are both non-directional and must stay
    that way in the math. They are not the same event and must stop reading
    the same in the record.

    TRUE FOR EXHAUSTION TOO (2026-07-27), deliberately. A provider skipped
    because its account is out of quota did not answer, so counting it as an
    abstention would say it read the evidence and held. The abstention
    arithmetic in consensus.py subtracts non-answers, so exhaustion has to sit
    inside this predicate. Use :func:`is_exhausted` to tell the two apart,
    which every reporting surface does.
    """
    return str(getattr(v, "source", "")) in (ERROR_SOURCE, EXHAUSTED_SOURCE)


def is_exhausted(v: ModelVerdict) -> bool:
    """Whether this verdict exists because the provider is out of quota.

    Distinct from a transient error (which may succeed next time) and from an
    abstention (the provider answered and held). A latched provider is not
    called at all, so there is no attempt to retry and nothing to diagnose per
    call: the condition belongs to the account, not to the request.
    """
    return str(getattr(v, "source", "")) == EXHAUSTED_SOURCE
