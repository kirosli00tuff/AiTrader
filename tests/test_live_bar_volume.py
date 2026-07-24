"""Live bar volume rides beside the trade price (2026-07-23).

fetch_prices keeps the latest-TRADE price (execution stays anchored to real
trades) and attaches the venue's latest MINUTE BAR volume as "<symbol>:v" /
"<symbol>:bar_ts". A missing or malformed bar attaches NOTHING: absence stays
absence, nothing is invented. A venue bar with v == 0 (quiet crypto minute)
is a genuine venue answer and is forwarded as such. No network: _http is
mocked with the exact shapes probed live on 2026-07-23.
"""
from __future__ import annotations

import market_data.alpaca_source as a


def _fake_http_full(method, url, headers, body=None):
    if "/stocks/trades/latest" in url:
        return {"trades": {"SPY": {"p": 700.0, "t": "T"}}}
    if "/stocks/bars/latest" in url:
        return {"bars": {"SPY": {"t": "2026-07-23T20:08:00Z", "v": 853,
                                 "o": 700.0, "c": 700.1, "n": 10}}}
    if "crypto/us/latest/trades" in url:
        return {"trades": {"BTC/USD": {"p": 65000.0}}}
    if "crypto/us/latest/bars" in url:
        # A quiet crypto minute: genuine v=0, n=0, quote-derived OHLC.
        return {"bars": {"BTC/USD": {"t": "2026-07-24T02:07:00Z", "v": 0,
                                     "n": 0}}}
    return {}


def test_fetch_prices_attaches_venue_bar_volume(monkeypatch):
    monkeypatch.setattr(a, "_data_keys", lambda: ("k", "s"))
    monkeypatch.setattr(a, "_http", _fake_http_full)
    out = a.fetch_prices(["SPY", "BTC/USD"])
    # Price is still the TRADE price.
    assert out["SPY"] == 700.0
    assert out["BTC/USD"] == 65000.0
    # Volume is the venue's own minute-bar v, keyed so the C++ flat reader
    # cannot confuse it with the bare symbol.
    assert out["SPY:v"] == 853.0
    assert out["SPY:bar_ts"] == "2026-07-23T20:08:00Z"
    # A genuine venue zero is forwarded as such, never dropped or invented.
    assert out["BTC/USD:v"] == 0.0
    assert out["source"] == "alpaca"


def test_missing_or_malformed_bar_attaches_nothing(monkeypatch):
    monkeypatch.setattr(a, "_data_keys", lambda: ("k", "s"))

    def fake_http(method, url, headers, body=None):
        if "/stocks/trades/latest" in url:
            return {"trades": {"SPY": {"p": 700.0}}}
        if "/stocks/bars/latest" in url:
            return {"bars": {"SPY": {"t": "", "v": -5}}}  # malformed
        return {}

    monkeypatch.setattr(a, "_http", fake_http)
    out = a.fetch_prices(["SPY"])
    assert out["SPY"] == 700.0
    # Absence stays absence: no key, no invented value, no carry-forward.
    assert "SPY:v" not in out
    assert "SPY:bar_ts" not in out
