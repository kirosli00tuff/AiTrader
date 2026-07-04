"""Parser tests for the whale live adapters against recorded-shape fixtures.

The fixtures under tests/fixtures/ are SYNTHETIC (hand-built to the documented
ClankApp / SEC EDGAR response shapes; see each file's `_provenance` and the
RETURN.md follow-up flag). They exercise the pure `_parse` methods so parsing is
verified with NO network call. Swap in a real capture later without touching the
test logic.
"""
import json
import os

from whale_signal.adapters import (ClankAppAdapter, Sec13FAdapter, _flag,
                                    _user_agent)

_FIX = os.path.join(os.path.dirname(__file__), "fixtures")


def _load(name):
    with open(os.path.join(_FIX, name), encoding="utf-8") as f:
        return json.load(f)


def test_clankapp_parse_exchange_flows():
    payload = _load("clankapp_sample.json")
    rows = ClankAppAdapter()._parse(payload, "BTC-USD")
    # Sub-min ($900) txn dropped; deposit->exchange = inflow, withdrawal = outflow.
    assert len(rows) == 2
    dirs = {r.direction for r in rows}
    assert dirs == {"inflow", "outflow"}
    assert all(r.source == "clankapp" and not r.delayed for r in rows)
    assert all(r.value_usd >= 500_000 for r in rows)
    entities = {r.entity for r in rows}
    assert "binance" in entities and "coinbase" in entities


def test_sec_edgar_parse_is_delayed_and_clean():
    payload = _load("sec_edgar_13f_sample.json")
    rows = Sec13FAdapter()._parse(payload, "AAPL")
    assert len(rows) == 2
    # CIK noise stripped, all 13F evidence flagged delayed.
    assert all(r.delayed for r in rows)
    assert all("(CIK" not in r.entity for r in rows)
    assert rows[0].entity == "BERKSHIRE HATHAWAY INC"
    assert rows[0].ts.startswith("2026-05-15")


def test_empty_payload_yields_no_rows():
    assert ClankAppAdapter()._parse({}, "BTC-USD") == []
    assert Sec13FAdapter()._parse({"hits": {"hits": []}}, "AAPL") == []


def test_live_disabled_by_default():
    # No opt-in flag -> adapters must not attempt live; fetch returns mock data.
    for var in ("WHALE_LIVE_ENABLED", "SEC_EDGAR_ENABLED"):
        os.environ.pop(var, None)
    assert _flag("WHALE_LIVE_ENABLED") is False
    assert _flag("SEC_EDGAR_ENABLED") is False
    crypto = ClankAppAdapter().fetch("BTC-USD")   # mock (offline)
    assert crypto and all(not a.delayed for a in crypto)
    equities = Sec13FAdapter().fetch("AAPL")       # mock (offline)
    assert equities and all(a.delayed for a in equities)


def test_user_agent_uses_env_contact_or_honest_placeholder():
    os.environ.pop("SEC_EDGAR_CONTACT_EMAIL", None)
    assert "set SEC_EDGAR_CONTACT_EMAIL" in _user_agent()
    os.environ["SEC_EDGAR_CONTACT_EMAIL"] = "ops@example.com"
    try:
        assert "ops@example.com" in _user_agent()
    finally:
        os.environ.pop("SEC_EDGAR_CONTACT_EMAIL", None)
