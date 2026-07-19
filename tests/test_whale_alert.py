"""Whale Alert crypto trial adapter tests (parser, heuristic, rate limit, cap).

tests/fixtures/whale_alert_transactions_sample.json is a REAL capture recorded
2026-07-15 from the Whale Alert v1 transactions endpoint (min_value 500000, last
hour), trimmed to 6 transactions that cover an exchange inflow (BTC/ETH to
Binance), an exchange outflow (USDT from Binance), and unknown-owner transfers.
It exercises the pure `_parse` method so parsing is verified with NO network
call. No test here makes a real network call: the one rate-limit test injects a
fake requests module.
"""
import json
import os

import yaml

from whale_signal import adapters as wa
from whale_signal.adapters import (WHALE_ALERT_ENABLED_ENV, WhaleAlertAdapter,
                                    default_adapters)
from whale_signal.scoring import activity_usefulness, score_whales, size_bucket

_FIX = os.path.join(os.path.dirname(__file__), "fixtures")


def _load(name):
    with open(os.path.join(_FIX, name), encoding="utf-8") as f:
        return json.load(f)


def _fixture():
    return _load("whale_alert_transactions_sample.json")


def test_parse_real_fixture_schema():
    rows = WhaleAlertAdapter()._parse(_fixture(), "BTC/USD")
    assert rows, "BTC query must parse the BTC transactions"
    assert all(r.source == "whale_alert" for r in rows)
    assert all(not r.delayed for r in rows)          # near real time, not delayed
    assert all(r.symbol == "BTC/USD" for r in rows)  # tagged to the queried symbol
    assert all(r.value_usd >= 500_000 for r in rows)  # min_value filter holds
    assert all(r.ts.endswith("Z") for r in rows)      # ISO8601 timestamp


def test_inflow_outflow_heuristic_reads_owner_type():
    # A transfer TO an exchange is an inflow (selling pressure). The BTC fixture
    # row that went to Binance must read inflow with the exchange as the entity.
    btc = WhaleAlertAdapter()._parse(_fixture(), "BTC/USD")
    inflow = [r for r in btc if r.entity == "Binance"]
    assert inflow and all(r.direction == "inflow" for r in inflow)
    # A transfer FROM an exchange is an outflow (accumulation). The USDT fixture
    # rows came from Binance.
    usdt = WhaleAlertAdapter()._parse(_fixture(), "USDT/USD")
    assert usdt and all(r.direction == "outflow" and r.entity == "Binance"
                        for r in usdt)


def test_size_bucket_reads_amount_usd():
    # The heuristic weights larger USD notionals higher, reading amount_usd.
    assert size_bucket(200_000_000) == 1.0
    assert size_bucket(15_000_000) == 0.8
    assert size_bucket(5_000_000) == 0.6
    assert size_bucket(150_000) == 0.4
    big = WhaleAlertAdapter()._parse(_fixture(), "BTC/USD")
    top = max(big, key=lambda r: r.value_usd)
    assert activity_usefulness(top) >= 0.6  # a multi-million transfer scores high


class _FakeResp:
    def __init__(self, status_code, headers=None):
        self.status_code = status_code
        self.headers = headers or {}

    def raise_for_status(self):
        pass

    def json(self):
        return {"transactions": []}


class _FakeRequests:
    def __init__(self, status_code):
        self._status = status_code
        self.calls = 0

    def get(self, *args, **kwargs):
        self.calls += 1
        return _FakeResp(self._status)


def test_rate_limit_429_retries_then_degrades(monkeypatch):
    # A persistent 429 retries the bounded number of times, then degrades to the
    # deterministic mock, never raising. No real sleep, no real network.
    fake = _FakeRequests(429)
    monkeypatch.setattr(wa, "_requests", lambda: fake)
    import time
    monkeypatch.setattr(time, "sleep", lambda *a, **k: None)
    monkeypatch.setenv(WHALE_ALERT_ENABLED_ENV, "true")
    ad = WhaleAlertAdapter()
    ad.key = "dummy-key"  # force live path without touching the real keystore
    rows = ad.fetch("BTC/USD")            # must not raise
    assert fake.calls == wa._RATE_LIMIT_MAX_RETRIES + 1  # retried then gave up
    assert isinstance(rows, list)         # degraded to mock, clean list


def test_absent_key_reports_not_live_without_raising(monkeypatch):
    monkeypatch.setattr(wa, "_resolve", lambda name: None)
    ad = WhaleAlertAdapter()
    assert ad.is_live() is False
    # Enabled but unkeyed: fetch never raises and default_adapters excludes it, so
    # behavior falls back to the existing SEC-only chain.
    monkeypatch.setenv(WHALE_ALERT_ENABLED_ENV, "true")
    assert ad.fetch("BTC/USD") is not None       # no raise
    assert all(a.source != "whale_alert" for a in default_adapters())


def test_disabled_by_default_excludes_whale_alert(monkeypatch):
    monkeypatch.delenv(WHALE_ALERT_ENABLED_ENV, raising=False)
    monkeypatch.setattr(wa, "_resolve", lambda name: "dummy-key")  # key present
    sources = {a.source for a in default_adapters()}
    assert "whale_alert" not in sources          # off by default => not in chain
    assert "sec_13f" in sources                  # SEC chain unchanged


def test_enabled_and_keyed_joins_chain(monkeypatch):
    monkeypatch.setenv(WHALE_ALERT_ENABLED_ENV, "true")
    monkeypatch.setattr(wa, "_resolve", lambda name: "dummy-key")
    sources = {a.source for a in default_adapters()}
    assert "whale_alert" in sources              # trial on + keyed => joins chain


def test_non_crypto_symbol_ignored():
    assert WhaleAlertAdapter().fetch("AAPL") == []  # equities never hit crypto feed


def test_cap_holds_and_two_sources_combine():
    # The unenforced whale_position_scale_cap was REMOVED 2026-07-18: config
    # must not claim a safety property no consumer provides. The real bound is
    # the whale ensemble weight plus the bounded signal below.
    cfg = yaml.safe_load(open("config/default_config.yaml", encoding="utf-8"))
    assert "whale_position_scale_cap" not in cfg["sizing"]
    # Both sources feed ONE whale factor: SEC (equity) + Whale Alert (crypto)
    # activities score into a single bounded advisory signal.
    wa_rows = WhaleAlertAdapter()._parse(_fixture(), "BTC/USD")
    from whale_signal.adapters import Sec13FAdapter
    sec_rows = Sec13FAdapter()._parse(_load("sec_edgar_13f_sample.json"), "AAPL")
    sig = score_whales(wa_rows + sec_rows, "BTC/USD")
    assert -1.0 <= sig.whale_bias <= 1.0
    assert 0.0 <= sig.whale_confidence <= 1.0
