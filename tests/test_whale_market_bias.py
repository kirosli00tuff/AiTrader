"""The whale market_bias never falls back to the catalyst hash constant.

The /score/whale handler used to read payload["catalyst"] as market_bias when
"bias" was absent. On the real path catalyst is a per-symbol HASH CONSTANT
from the mock catalyst provider, so the whale contradiction flag was judged
against an invented market bias. Fixed 2026-07-23: market_bias comes ONLY
from an explicit "bias"; absent means 0.0, which the scorer treats as
no-market-read (the contradiction check disarms rather than fires on
fiction). Mutation: restoring the catalyst fallback fails the first test.
"""
from __future__ import annotations

import pytest


def _capture(monkeypatch, server):
    seen = {}

    def fake_whale_signal_for(symbol, market_bias=0.0, **kwargs):
        seen["symbol"] = symbol
        seen["market_bias"] = market_bias

        class _Sig:
            def to_dict(self):
                return {"bias": 0.0, "confidence": 0.0, "edge": 0.0}

        return _Sig(), []

    monkeypatch.setattr(server, "whale_signal_for", fake_whale_signal_for)
    return seen


def test_catalyst_never_stands_in_for_market_bias(monkeypatch):
    server = pytest.importorskip("python_bridge.server")
    seen = _capture(monkeypatch, server)
    server._handle("/score/whale", {"symbol": "BTC/USD", "catalyst": 0.9})
    # The hash-constant catalyst is NOT a market bias: absent bias reads 0.0.
    assert seen["market_bias"] == 0.0


def test_explicit_bias_still_reaches_the_scorer(monkeypatch):
    server = pytest.importorskip("python_bridge.server")
    seen = _capture(monkeypatch, server)
    server._handle("/score/whale", {"symbol": "BTC/USD", "bias": 0.4,
                                    "catalyst": 0.9})
    assert seen["market_bias"] == 0.4
