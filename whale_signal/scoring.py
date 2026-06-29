"""Whale-signal scoring + actor ranking (useful-vs-noisy).

Turns raw whale observations into the exact advisory output fields, and ranks
actors by a historical-usefulness heuristic so noisy actors can be filtered.
Advisory only: the result is one weighted factor downstream, never a controller.
"""
from __future__ import annotations

import hashlib
import math
from dataclasses import dataclass, asdict

from .adapters import WhaleActivity

_BULLISH = {"inflow", "long"}
_BEARISH = {"outflow", "short"}


@dataclass
class WhaleSignal:
    whale_bias: float            # signed [-1,1]
    whale_confidence: float      # [0,1]
    whale_flow_direction: str    # bullish | bearish | neutral
    whale_activity_score: float  # [0,1]
    whale_follow_signal: int     # 1 if actionable
    whale_contradiction_flag: int  # 1 if contradicts market/consensus bias
    whale_regime_label: str      # accumulation | distribution | mixed | quiet
    delayed_only: int = 0        # 1 if all evidence is DELAYED (e.g. 13F only)

    def to_dict(self) -> dict:
        d = asdict(self)
        # Bridge-compatible aliases consumed by the C++ engine.
        d["bias"] = self.whale_bias
        d["confidence"] = self.whale_confidence
        d["edge"] = round(0.02 * abs(self.whale_bias) * self.whale_activity_score, 4)
        return d


def actor_usefulness(entity: str) -> float:
    """Deterministic historical-usefulness score in [0,1] for an actor.

    Stands in for a learned per-actor hit-rate. Used to weight + filter actors.
    """
    h = int(hashlib.sha256(("useful:" + entity).encode()).hexdigest(), 16)
    return (h % 1000) / 1000.0


def rank_actors(activities: list[WhaleActivity],
                min_usefulness: float = 0.0) -> list[tuple[str, float]]:
    """Rank distinct actors by usefulness, optionally filtering noisy ones."""
    scores = {a.entity: actor_usefulness(a.entity) for a in activities}
    ranked = sorted(scores.items(), key=lambda kv: kv[1], reverse=True)
    return [(e, s) for e, s in ranked if s >= min_usefulness]


def score_whales(activities: list[WhaleActivity], symbol: str,
                 market_bias: float = 0.0, min_activity_score: float = 0.60,
                 min_actor_usefulness: float = 0.55,
                 contradiction_enabled: bool = True) -> WhaleSignal:
    """Score whale activity for a symbol into the advisory whale signal."""
    relevant = [a for a in activities if a.symbol == symbol]
    if not relevant:
        return WhaleSignal(0.0, 0.0, "neutral", 0.0, 0, 0, "quiet", 0)

    # Weight each observation by value and actor usefulness; filter noisy actors.
    weighted_dir = 0.0
    total_w = 0.0
    total_value = 0.0
    delayed_count = 0
    for a in relevant:
        usefulness = actor_usefulness(a.entity)
        if usefulness < min_actor_usefulness:
            continue  # drop noisy actor
        sign = 1.0 if a.direction in _BULLISH else (-1.0 if a.direction in _BEARISH else 0.0)
        w = math.log10(max(10.0, a.value_usd)) * usefulness
        # DELAYED disclosures (13F) get down-weighted — context, not live flow.
        if a.delayed:
            w *= 0.4
            delayed_count += 1
        weighted_dir += sign * w
        total_w += w
        total_value += a.value_usd

    if total_w <= 0.0:
        return WhaleSignal(0.0, 0.0, "neutral", 0.0, 0, 0, "quiet",
                           int(delayed_count == len(relevant)))

    bias = max(-1.0, min(1.0, weighted_dir / total_w))
    # Activity score scales with count + notional, saturating to 1.
    activity_score = max(0.0, min(1.0,
        0.2 * len(relevant) + min(0.8, math.log10(max(10.0, total_value)) / 10.0)))
    confidence = max(0.0, min(1.0, 0.4 + 0.5 * abs(bias) * activity_score))

    if bias > 0.15:
        flow = "bullish"
    elif bias < -0.15:
        flow = "bearish"
    else:
        flow = "neutral"

    follow = int(activity_score >= min_activity_score and abs(bias) > 0.2)

    contradiction = 0
    if contradiction_enabled and market_bias != 0.0:
        if (bias > 0) != (market_bias > 0) and abs(bias) > 0.2:
            contradiction = 1

    if activity_score < 0.2:
        regime = "quiet"
    elif bias > 0.3:
        regime = "accumulation"
    elif bias < -0.3:
        regime = "distribution"
    else:
        regime = "mixed"

    delayed_only = int(delayed_count == len(relevant))
    return WhaleSignal(
        whale_bias=round(bias, 4),
        whale_confidence=round(confidence, 4),
        whale_flow_direction=flow,
        whale_activity_score=round(activity_score, 4),
        whale_follow_signal=follow,
        whale_contradiction_flag=contradiction,
        whale_regime_label=regime,
        delayed_only=delayed_only,
    )
