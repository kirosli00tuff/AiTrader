"""Tests for the Finnhub discovery client: parsers, rate limiter, 429 backoff.

No network. Transport is driven through the client's ``opener`` injection seam,
and the parsers run against the recorded fixture shapes.

Fixture status: SYNTHETIC. No FINNHUB_API_KEY resolves in this environment, so a
real response could not be recorded. The host IS up (an unauthenticated probe
returned HTTP 401 "Please use an API key"), so the blocker is a missing
credential, not a dead host. See tests/fixtures/finnhub_SYNTHETIC.json.
"""
from __future__ import annotations

import json
import logging
import os

import pytest

from discovery import finnhub_source as fh

_FIXTURE = os.path.join(os.path.dirname(__file__), "fixtures",
                        "finnhub_SYNTHETIC.json")

# A distinctive NON-secret-shaped sentinel standing in for a resolved key. It is
# deliberately not credential-shaped so the pre-commit secret scanner does not
# flag it; what matters is only that this exact string never reaches a log line
# or a cache key.
CANARY_KEY = "CANARY-FINNHUB-KEY-MUST-NOT-APPEAR-4k3j2h"


@pytest.fixture(scope="module")
def fx() -> dict:
    with open(_FIXTURE, encoding="utf-8") as f:
        return json.load(f)


def _opener(status: int, body: object, headers: dict | None = None):
    """Build an opener returning a canned response. Records the URLs it saw."""
    calls: list[str] = []

    def _open(url: str):
        calls.append(url)
        raw = body if isinstance(body, bytes) else json.dumps(body).encode()
        return status, raw, headers or {}

    _open.calls = calls  # type: ignore[attr-defined]
    return _open


# --- parsers ----------------------------------------------------------------

def test_parse_quote_normalizes_fixture(fx):
    q = fh.parse_quote(fx["quote"])
    assert q["price"] == 231.44
    assert q["change_pct"] == pytest.approx(1.8129)
    assert q["high"] == 233.1 and q["low"] == 227.8
    assert q["prev_close"] == 227.32


def test_parse_quote_rejects_zero_price(fx):
    # An unknown symbol returns zeros. No price means no signal, not a bad one.
    assert fh.parse_quote(fx["quote_no_price"]) == {}
    assert fh.parse_quote(None) == {}
    assert fh.parse_quote({"c": "not-a-number"}) == {}


def test_parse_news_sentiment(fx):
    s = fh.parse_news_sentiment(fx["news_sentiment"])
    assert s["score"] == 0.82
    assert s["bullish_pct"] == 0.81 and s["bearish_pct"] == 0.19
    assert s["articles_last_week"] == 42


def test_parse_news_sentiment_defaults_to_neutral():
    # A payload with no score is neutral (0.5), never a false directional signal.
    assert fh.parse_news_sentiment({})["score"] == 0.5


def test_parse_recommendations_scores_latest_period(fx):
    r = fh.parse_recommendations(fx["recommendation_trends"])
    # The newest period wins even though both are present.
    assert r["period"] == "2026-07-01"
    assert r["strong_buy"] == 14 and r["total"] == 43
    # (14*1 + 18*0.5 + 9*0 + 2*-0.5 + 0*-1) / 43 = 22/43
    assert r["score"] == pytest.approx(22.0 / 43.0, abs=1e-4)


def test_parse_recommendations_handles_empty():
    assert fh.parse_recommendations([]) == {}
    assert fh.parse_recommendations(None) == {}
    assert fh.parse_recommendations([{"strongBuy": 0, "buy": 0, "hold": 0,
                                      "sell": 0, "strongSell": 0}]) == {}


def test_parse_basic_financials(fx):
    f = fh.parse_basic_financials(fx["basic_financials"])
    assert f["roe_ttm"] == 147.25
    assert f["pe_ttm"] == 34.6
    assert f["week52_high"] == 260.1 and f["week52_low"] == 164.08


def test_parse_basic_financials_missing_metric_is_none():
    # A missing metric is None, NOT 0.0: the screen must tell "no data" from a
    # real zero, or thin coverage would read as poor quality.
    f = fh.parse_basic_financials({"metric": {"roeTTM": 12.0}})
    assert f["roe_ttm"] == 12.0
    assert f["pe_ttm"] is None
    assert fh.parse_basic_financials({}) == {}


def test_parse_earnings_calendar(fx):
    rows = fh.parse_earnings_calendar(fx["earnings_calendar"])
    assert len(rows) == 1
    assert rows[0]["symbol"] == "AAPL" and rows[0]["date"] == "2026-07-28"
    assert rows[0]["eps_estimate"] == 1.64
    assert fh.parse_earnings_calendar({}) == []


# --- rate limiter -----------------------------------------------------------

def test_rate_limiter_allows_up_to_the_ceiling_then_refuses():
    lim = fh.RateLimiter(calls=3, window=60.0)
    assert all(lim.try_acquire(now=100.0) for _ in range(3))
    # The 4th inside the window is refused: the free tier is 60/min and the
    # limiter is what keeps a universe sweep under it.
    assert lim.try_acquire(now=100.0) is False


def test_rate_limiter_window_rolls():
    lim = fh.RateLimiter(calls=2, window=60.0)
    assert lim.try_acquire(now=0.0)
    assert lim.try_acquire(now=0.0)
    assert lim.try_acquire(now=30.0) is False
    # Past the window the earlier starts fall out and slots free again.
    assert lim.try_acquire(now=61.0)


def test_retry_after_honors_header_and_caps():
    assert fh.retry_after_seconds({"Retry-After": "2"}, 0) == 2.0
    assert (fh.retry_after_seconds({"retry-after": "999"}, 0)
            == fh.RATE_LIMIT_BACKOFF_CAP_S)
    # No header falls back to bounded exponential backoff.
    assert fh.retry_after_seconds({}, 0) == 1.0
    assert fh.retry_after_seconds({}, 1) == 2.0
    assert fh.retry_after_seconds({}, 9) == fh.RATE_LIMIT_BACKOFF_CAP_S
    # A malformed header never raises.
    assert fh.retry_after_seconds({"Retry-After": "soon"}, 0) == 1.0


# --- transport --------------------------------------------------------------

def test_no_key_means_no_call(monkeypatch):
    monkeypatch.delenv("FINNHUB_API_KEY", raising=False)
    monkeypatch.setattr(fh, "credentials", None)
    opener = _opener(200, {"c": 1.0})
    c = fh.FinnhubClient(opener=opener)
    assert c.quote("AAPL") is None
    # With no key resolvable the client must not touch the network at all.
    assert opener.calls == []


def test_429_retries_then_gives_up(monkeypatch, fx):
    monkeypatch.setattr(fh.time, "sleep", lambda _s: None)  # no real waiting
    opener = _opener(429, fx["rate_limited"], {"Retry-After": "0"})
    c = fh.FinnhubClient(api_key=CANARY_KEY, opener=opener)
    assert c.quote("AAPL") is None
    # The initial attempt plus RATE_LIMIT_MAX_RETRIES retries, then it degrades.
    assert len(opener.calls) == fh.RATE_LIMIT_MAX_RETRIES + 1
    assert c.rate_limited == fh.RATE_LIMIT_MAX_RETRIES + 1


def test_429_then_success(monkeypatch, fx):
    monkeypatch.setattr(fh.time, "sleep", lambda _s: None)
    seq = [(429, json.dumps(fx["rate_limited"]).encode(), {}),
           (200, json.dumps(fx["quote"]).encode(), {})]
    calls: list[str] = []

    def _open(url: str):
        calls.append(url)
        return seq[len(calls) - 1]

    c = fh.FinnhubClient(api_key=CANARY_KEY, opener=_open)
    q = c.quote("AAPL")
    assert q is not None and q["c"] == 231.44
    assert len(calls) == 2


def test_non_429_error_fails_fast(fx):
    # 401 is not retryable: a wrong key will still be wrong on the retry.
    opener = _opener(401, {"error": "Please use an API key."})
    c = fh.FinnhubClient(api_key="wrong", opener=opener)
    assert c.quote("AAPL") is None
    assert len(opener.calls) == 1


def test_cache_prevents_a_second_fetch(fx):
    opener = _opener(200, fx["quote"])
    c = fh.FinnhubClient(api_key=CANARY_KEY, opener=opener)
    assert c.quote("AAPL") is not None
    assert c.quote("AAPL") is not None
    # One universe pass must not re-fetch what it already holds.
    assert len(opener.calls) == 1
    c.clear_cache()
    assert c.quote("AAPL") is not None
    assert len(opener.calls) == 2


def test_transport_error_degrades_to_none():
    def _boom(_url: str):
        raise OSError("connection reset")

    c = fh.FinnhubClient(api_key=CANARY_KEY, opener=_boom)
    # A Finnhub outage pauses discovery, it never breaks the engine.
    assert c.quote("AAPL") is None


def test_unparseable_body_degrades_to_none():
    c = fh.FinnhubClient(api_key=CANARY_KEY,
                         opener=_opener(200, b"<html>gateway error</html>"))
    assert c.quote("AAPL") is None


# --- key safety -------------------------------------------------------------

def test_key_never_appears_in_logs(caplog):
    """The token rides in the URL, so nothing may log a URL or an exception body."""
    caplog.set_level(logging.DEBUG, logger="discovery.finnhub")

    def _boom(_url: str):
        # A transport error whose text embeds the URL, and so the key.
        raise OSError(f"failed to reach https://finnhub.io/api/v1/quote?"
                      f"symbol=AAPL&token={CANARY_KEY}")

    c = fh.FinnhubClient(api_key=CANARY_KEY, opener=_boom)
    assert c.quote("AAPL") is None

    for status in (401, 429, 500):
        c2 = fh.FinnhubClient(api_key=CANARY_KEY, opener=_opener(status, {"e": 1}))
        c2._get("quote", {"symbol": "AAPL"})

    assert CANARY_KEY not in caplog.text
    assert "token=" not in caplog.text


def test_key_never_reaches_the_cache_key():
    c = fh.FinnhubClient(api_key=CANARY_KEY, opener=_opener(200, {"c": 1.0}))
    ck = c._cache_key("quote", {"symbol": "AAPL", "token": CANARY_KEY})
    assert CANARY_KEY not in ck
    assert ck == "quote?symbol=AAPL"


def test_resolve_key_prefers_keystore(monkeypatch):
    monkeypatch.setenv("FINNHUB_API_KEY", "from-env")

    class _Creds:
        @staticmethod
        def get_credential(name):
            assert name == "finnhub_key"
            return "from-keystore"

    monkeypatch.setattr(fh, "credentials", _Creds)
    assert fh.resolve_key() == "from-keystore"


def test_resolve_key_falls_back_to_env(monkeypatch):
    monkeypatch.setenv("FINNHUB_API_KEY", "from-env")

    class _Creds:
        @staticmethod
        def get_credential(_name):
            return None

    monkeypatch.setattr(fh, "credentials", _Creds)
    assert fh.resolve_key() == "from-env"
    assert fh.is_live() is True


def test_finnhub_key_is_in_the_credential_registry():
    # The GUI manages the key through the same encrypted keystore as every other
    # credential, so it is never hardcoded and never committed.
    from account_manager import credentials
    assert "finnhub_key" in credentials.CREDENTIALS
    spec = credentials.CREDENTIALS["finnhub_key"]
    assert spec.secret is True
    assert "FINNHUB_API_KEY" in spec.env_candidates
