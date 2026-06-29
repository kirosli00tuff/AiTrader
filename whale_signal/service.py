"""Whale-signal service: fetch from all adapters, then score."""
from __future__ import annotations

from .adapters import default_adapters
from .scoring import score_whales, WhaleSignal


def fetch_all(symbol: str, adapters=None):
    adapters = adapters or default_adapters()
    activities = []
    for ad in adapters:
        try:
            activities.extend(ad.fetch(symbol))
        except NotImplementedError:
            # Live path not implemented; skip (mock fallback handles offline).
            continue
    return activities


def whale_signal_for(symbol: str, market_bias: float = 0.0,
                     min_activity_score: float = 0.60,
                     min_actor_usefulness: float = 0.55,
                     contradiction_enabled: bool = True,
                     adapters=None) -> tuple[WhaleSignal, list]:
    """Return (scored whale signal, raw activities) for a symbol."""
    activities = fetch_all(symbol, adapters)
    sig = score_whales(
        activities, symbol, market_bias=market_bias,
        min_activity_score=min_activity_score,
        min_actor_usefulness=min_actor_usefulness,
        contradiction_enabled=contradiction_enabled,
    )
    return sig, activities


if __name__ == "__main__":
    import json

    for sym in ["BTC-USD", "AAPL", "PRES-2028-YES"]:
        sig, acts = whale_signal_for(sym)
        print(sym, json.dumps(sig.to_dict()), f"({len(acts)} activities)")
