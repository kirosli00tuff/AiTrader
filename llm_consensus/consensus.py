"""Multi-LLM consensus ensemble (the "council").

Produces a consensus directional verdict from several LLM providers. Three real
providers (OpenAI / Anthropic / Google) plug in behind API keys; when a key is
absent that provider degrades to a clearly-labelled deterministic mock, so the
offline demo needs no keys. A cheap Gemini-Flash base-check gate can skip the
whole council for low-signal setups (cost control).

Output is ADVISORY ONLY — it enters the C++ factor-combination engine as
weighted factors and can never bypass Layer-1 risk.

Which council runs is controlled by config (``config/default_config.yaml``):
  * llm.use_real_council (default false) -> real providers vs mock.
  * llm.gate_enabled     (default true)  -> run the base-check gate first.
The engine only swaps in the real council when use_real_council is true AND it
is launched with ``--bridge`` (see core/main.cpp + python_bridge).
"""
from __future__ import annotations

# Re-exported here so existing imports (`from llm_consensus.consensus import ...`)
# keep working after the split into focused modules.
from .config_access import (  # noqa: F401
    gate_enabled, llm_model_names, slot_weight, use_real_council,
)
from .gate import AlwaysProceedGate, GateDecision, GeminiFlashGate  # noqa: F401
from .providers import (  # noqa: F401
    AnthropicProvider, GeminiProvider, LLMProvider, MockLLMProvider,
    OpenAIProvider,
)
from .verdicts import (  # noqa: F401
    ConsensusResult, ModelVerdict, _det_unit, bias_to_verdict,
)

# Provider "personality" skews — kept identical to the original ensemble so the
# offline mock behaviour (and its tests) are unchanged.
_SLOT_SKEW: dict[str, float] = {
    "llm_primary": 0.10,
    "llm_secondary": -0.05,
    "llm_tertiary": 0.0,
}


def default_providers(cfg_path: str | None = None) -> list[LLMProvider]:
    """The three ensemble slots as deterministic offline MOCK providers."""
    names = llm_model_names(cfg_path)
    return [
        MockLLMProvider(name=slot, weight=slot_weight(slot, cfg_path),
                        skew=_SLOT_SKEW[slot], model_id=names.get(slot, ""))
        for slot in ("llm_primary", "llm_secondary", "llm_tertiary")
    ]


def real_providers(cfg_path: str | None = None) -> list[LLMProvider]:
    """The three ensemble slots as REAL API-backed providers.

    Slot -> provider mapping matches the ``llm_models`` config block:
      llm_primary   = OpenAI    (gpt-5.5)
      llm_secondary = Anthropic (claude-opus-4-8)
      llm_tertiary  = Google    (gemini-3.1-pro)
    Each still degrades to a labelled mock when its key is absent.
    """
    names = llm_model_names(cfg_path)
    return [
        OpenAIProvider(name="llm_primary",
                       weight=slot_weight("llm_primary", cfg_path),
                       model_id=names.get("llm_primary", "gpt-5.5"),
                       skew=_SLOT_SKEW["llm_primary"]),
        AnthropicProvider(name="llm_secondary",
                          weight=slot_weight("llm_secondary", cfg_path),
                          model_id=names.get("llm_secondary", "claude-opus-4-8"),
                          skew=_SLOT_SKEW["llm_secondary"]),
        GeminiProvider(name="llm_tertiary",
                       weight=slot_weight("llm_tertiary", cfg_path),
                       model_id=names.get("llm_tertiary", "gemini-3.1-pro"),
                       skew=_SLOT_SKEW["llm_tertiary"]),
    ]


def build_council(cfg_path: str | None = None) -> list[LLMProvider]:
    """Real council when llm.use_real_council is set, else the mock council."""
    if use_real_council(cfg_path):
        return real_providers(cfg_path)
    return default_providers(cfg_path)


def build_gate(cfg_path: str | None = None):
    """The base-check gate, or a no-op AlwaysProceedGate when disabled."""
    if not gate_enabled(cfg_path):
        return AlwaysProceedGate(reason="gate disabled by config", source="disabled")
    return GeminiFlashGate(model_id=llm_model_names(cfg_path).get(
        "llm_gate", "gemini-3-flash"))


def _flat_consensus(gate: GateDecision) -> ConsensusResult:
    """Neutral council verdict returned when the gate skips the review."""
    return ConsensusResult(
        bias=0.0, confidence=0.0, edge=0.0, verdict=bias_to_verdict(0.0),
        agreement_count=0, per_model=[], gate=gate.to_dict())


def consensus(state: dict, providers: list[LLMProvider] | None = None,
              gate=None, cfg_path: str | None = None) -> ConsensusResult:
    """Weighted ensemble of provider verdicts into one consensus.

    Runs the base-check gate first; if it declines, returns a flat verdict and
    skips the (expensive) providers entirely. The ensemble math itself is
    unchanged from the original mock-only implementation.
    """
    g = gate if gate is not None else build_gate(cfg_path)
    decision = g.should_review(state)
    if not decision.proceed:
        return _flat_consensus(decision)

    prov = providers if providers is not None else build_council(cfg_path)
    verdicts = [p.score(state) for p in prov]
    wsum = sum(p.weight for p in prov) or 1.0

    bias = sum(v.bias * p.weight for v, p in zip(verdicts, prov)) / wsum
    conf = sum(v.confidence * p.weight for v, p in zip(verdicts, prov)) / wsum
    edge = sum(v.edge * p.weight for v, p in zip(verdicts, prov)) / wsum

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
        gate=decision.to_dict(),
    )


def council_status_line(cfg_path: str | None = None) -> str:
    """One-line, unambiguous statement of which council + gate are active.

    Printed at bridge startup so it is never ambiguous whether the REAL council
    or the MOCK council is running (see Task 5 startup requirement).
    """
    real = use_real_council(cfg_path)
    names = llm_model_names(cfg_path)
    if real:
        council = (f"REAL council [{names.get('llm_primary', 'gpt-5.5')}, "
                   f"{names.get('llm_secondary', 'claude-opus-4-8')}, "
                   f"{names.get('llm_tertiary', 'gemini-3.1-pro')}]")
    else:
        council = "MOCK council (deterministic offline stand-ins)"
    if gate_enabled(cfg_path):
        gate = f"base-check gate ON ({names.get('llm_gate', 'gemini-3-flash')})"
    else:
        gate = "base-check gate OFF"
    return f"LLM council: {council}; {gate}"


if __name__ == "__main__":
    import json

    s = {"symbol": "BTC-USD", "ret_5": 0.02, "imbalance": 0.3, "catalyst": 0.4}
    print(council_status_line())
    print(json.dumps(consensus(s).to_dict(), indent=2))
