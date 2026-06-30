"""Multi-LLM consensus ensemble.

Produces a consensus directional verdict from several LLM "providers". Real
providers (OpenAI / Anthropic / etc.) plug in behind API keys; for the offline
demo every provider is a deterministic MOCK so no keys are required. Output is
ADVISORY ONLY — it enters the C++ factor-combination engine as weighted factors
and can never bypass Layer-1 risk.
"""
from __future__ import annotations

import hashlib
import math
import os
from dataclasses import dataclass, field
from typing import Protocol


def _det_unit(seed: str) -> float:
    h = int(hashlib.sha256(seed.encode()).hexdigest(), 16)
    return (h % 1_000_000) / 1_000_000.0


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


@dataclass
class ModelVerdict:
    model: str
    bias: float          # signed [-1, 1]
    confidence: float    # [0, 1]
    edge: float          # expected edge
    verdict: str
    rationale: str = ""


@dataclass
class ConsensusResult:
    bias: float
    confidence: float
    edge: float
    verdict: str
    agreement_count: int
    per_model: list[ModelVerdict] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "bias": round(self.bias, 4),
            "confidence": round(self.confidence, 4),
            "edge": round(self.edge, 4),
            "verdict": self.verdict,
            "agreement_count": self.agreement_count,
            "per_model": [vars(m) for m in self.per_model],
        }


class LLMProvider(Protocol):
    name: str
    weight: float

    def score(self, state: dict) -> ModelVerdict: ...


@dataclass
class MockLLMProvider:
    """Deterministic offline LLM stand-in.

    Derives a stable directional read from the market-state features plus a
    provider-specific perturbation, so different "models" mildly disagree —
    which is what makes the consensus + agreement count meaningful.
    """

    name: str
    weight: float = 0.2
    skew: float = 0.0  # provider personality (bull/bear lean)
    model_id: str = ""  # concrete model identity (e.g. "gpt-5.5"), from config

    def score(self, state: dict) -> ModelVerdict:
        sym = str(state.get("symbol", "?"))
        ret5 = float(state.get("ret_5", 0.0))
        imbalance = float(state.get("imbalance", 0.0))
        catalyst = float(state.get("catalyst", 0.0))
        vol = float(state.get("volatility", 0.0))
        noise = _det_unit(self.name + sym) - 0.5
        raw = ret5 * 22.0 + imbalance * 0.3 + catalyst * 0.4 + self.skew + noise
        bias = math.tanh(raw)
        confidence = max(0.0, min(1.0, 0.55 + 0.4 * abs(bias) - vol * 0.8))
        edge = max(0.0, 0.03 * abs(bias) + 0.005)
        return ModelVerdict(
            model=self.name,
            bias=round(bias, 4),
            confidence=round(confidence, 4),
            edge=round(edge, 4),
            verdict=bias_to_verdict(bias),
            rationale=f"mock read on {sym}",
        )


class OpenAIProvider:
    """TODO: real OpenAI-backed provider. Requires OPENAI_API_KEY.

    Kept structurally so a real key can be dropped in. Falls back to mock when
    no key is configured so the demo always runs.
    """

    def __init__(self, name: str = "gpt", weight: float = 0.2):
        self.name = name
        self.weight = weight
        self._fallback = MockLLMProvider(name=name, weight=weight)

    def score(self, state: dict) -> ModelVerdict:
        if not os.environ.get("OPENAI_API_KEY"):
            return self._fallback.score(state)
        # TODO: implement real chat-completion call + structured parsing.
        raise NotImplementedError("Live OpenAI provider not implemented.")


def llm_model_names(cfg_path: str | None = None) -> dict[str, str]:
    """Return the configured concrete model id per LLM ensemble slot.

    Single source of truth = the ``llm_models`` block in the engine config
    (overridable via ``MAL_CONFIG_PATH``). Never hardcoded here so the names
    stay accurate whenever the config changes. Empty dict if unavailable.
    """
    path = cfg_path or os.environ.get("MAL_CONFIG_PATH")
    if not path:
        path = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            "config", "default_config.yaml")
    try:
        import yaml
        with open(path) as fh:
            cfg = yaml.safe_load(fh) or {}
        names = cfg.get("llm_models", {}) or {}
        return {str(k): str(v) for k, v in names.items()}
    except Exception:
        return {}


def default_providers() -> list[LLMProvider]:
    """The three ensemble LLM slots, mapped to the C++ weight factor names.

    Each slot's concrete model id is sourced from the config's ``llm_models``
    block so the live identity is recorded on every provider/verdict.
    """
    names = llm_model_names()
    return [
        MockLLMProvider(name="llm_primary", weight=0.27, skew=0.10,
                        model_id=names.get("llm_primary", "")),
        MockLLMProvider(name="llm_secondary", weight=0.18, skew=-0.05,
                        model_id=names.get("llm_secondary", "")),
        MockLLMProvider(name="llm_tertiary", weight=0.12, skew=0.0,
                        model_id=names.get("llm_tertiary", "")),
    ]


def consensus(state: dict, providers: list[LLMProvider] | None = None) -> ConsensusResult:
    """Weighted ensemble of provider verdicts into one consensus."""
    providers = providers or default_providers()
    verdicts = [p.score(state) for p in providers]
    wsum = sum(p.weight for p in providers) or 1.0

    bias = sum(v.bias * p.weight for v, p in zip(verdicts, providers)) / wsum
    conf = sum(v.confidence * p.weight for v, p in zip(verdicts, providers)) / wsum
    edge = sum(v.edge * p.weight for v, p in zip(verdicts, providers)) / wsum

    net = 1 if bias > 0 else (-1 if bias < 0 else 0)
    agreement = sum(
        1 for v in verdicts if net != 0 and (1 if v.bias > 0 else -1) == net
    )
    return ConsensusResult(
        bias=bias,
        confidence=conf,
        edge=edge,
        verdict=bias_to_verdict(bias),
        agreement_count=agreement,
        per_model=verdicts,
    )


if __name__ == "__main__":
    import json

    s = {"symbol": "BTC-USD", "ret_5": 0.02, "imbalance": 0.3, "catalyst": 0.4}
    print(json.dumps(consensus(s).to_dict(), indent=2))
