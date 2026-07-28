"""News / catalyst fetchers (Python side).

The C++ core (`news_ingestion/news_ingestion.cpp`) owns catalyst *state*; messy
live-API parsing lives here in Python. For the offline demo every fetcher has a
deterministic MOCK fallback so no API keys are required.

TODO: wire real providers (NewsAPI, Benzinga, RSS) behind `live=True`.
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass, asdict


@dataclass
class Catalyst:
    symbol: str
    score: float       # [-1, 1] directional pressure
    importance: float  # [0, 1]
    headline: str
    source: str


def _det_unit(seed: str) -> float:
    h = int(hashlib.sha256(seed.encode()).hexdigest(), 16)
    return (h % 10_000) / 10_000.0


def fetch_catalyst(symbol: str, live: bool = False) -> Catalyst:
    """Return a catalyst score for a symbol. Mock unless live and configured."""
    if live:
        # TODO: implement real news provider integration.
        raise NotImplementedError("Live news fetch not implemented; use mock.")
    score = _det_unit("score:" + symbol) * 2 - 1
    importance = _det_unit("imp:" + symbol)
    return Catalyst(
        symbol=symbol,
        score=round(score, 4),
        importance=round(importance, 4),
        headline=f"Mock catalyst for {symbol}",
        source="mock",
    )


def fetch_many(symbols: list[str], live: bool = False) -> list[dict]:
    return [asdict(fetch_catalyst(s, live=live)) for s in symbols]


if __name__ == "__main__":
    import json

    print(json.dumps(fetch_many(["BTC-USD", "AAPL", "PRES-2028"]), indent=2))
