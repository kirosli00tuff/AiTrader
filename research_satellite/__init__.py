"""Research satellite sleeve: LLM deep-research thesis generation.

The research_satellite sleeve uses the LLM council in a deeper research mode to
produce a structured long-term thesis (direction, conviction, horizon, rationale)
for a candidate instrument. It is cost-controlled (the Haiku gate screens a
candidate before the full council runs, the same pattern the quant council uses)
and never a sole controller: the C++ engine enforces the hard satellite cap, the
conviction threshold, and the RiskGate on every resulting order.
"""
from .research import research_thesis

__all__ = ["research_thesis"]
