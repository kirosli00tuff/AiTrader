"""Whale / smart-money advisory signal (Layer 4). Advisory only.

Sources: Apify Polymarket whale-tracker, Whale Alert API, SEC API 13F (DELAYED
institutional disclosure). Every adapter has a deterministic MOCK fallback so
the demo runs offline with no API keys.
"""
from .adapters import (  # noqa: F401
    ApifyWhaleAdapter,
    WhaleAlertAdapter,
    Sec13FAdapter,
    WhaleActivity,
)
from .scoring import score_whales, rank_actors, WhaleSignal  # noqa: F401
from .service import whale_signal_for  # noqa: F401
