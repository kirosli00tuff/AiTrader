"""Whale / smart-money advisory signal (Layer 4). Advisory only.

Free-first sources: ClankApp (free crypto/on-chain, DEFAULT) and SEC EDGAR 13F
(free, no key, DELAYED institutional disclosure). Whale Alert remains available
as an optional key-gated alternative. Every adapter has a deterministic MOCK
fallback so the app runs offline with no API keys.
"""
from .adapters import (  # noqa: F401
    ClankAppAdapter,
    WhaleAlertAdapter,
    Sec13FAdapter,
    WhaleActivity,
)
from .scoring import score_whales, rank_actors, WhaleSignal  # noqa: F401
from .service import whale_signal_for  # noqa: F401
