"""Multi-LLM consensus advisory factor (Layer-3 sibling, advisory only)."""
from .consensus import (  # noqa: F401
    LLMProvider,
    MockLLMProvider,
    ModelVerdict,
    ConsensusResult,
    consensus,
    default_providers,
)
