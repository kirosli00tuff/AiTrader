"""Whale / smart-money advisory signal (Layer 4). Advisory only.

Active source: SEC EDGAR 13F (free, keyless, DELAYED institutional disclosure)
is the sole adapter in the active default chain. Whale Alert stays importable as
a reserved optional crypto feed, off the default chain, and Unusual Whales Pro is
a reserved paid upgrade (env name only, no adapter). ClankApp was removed on
2026-07-10 (dead host). Every adapter has a deterministic MOCK fallback so the
app runs offline with no API keys.
"""
from .adapters import (  # noqa: F401
    WhaleAlertAdapter,
    Sec13FAdapter,
    WhaleActivity,
)
from .scoring import score_whales, rank_actors, WhaleSignal  # noqa: F401
from .service import whale_signal_for  # noqa: F401
