"""Parser tests for the whale live adapters against recorded fixtures.

tests/fixtures/sec_edgar_13f_sample.json is a REAL capture recorded 2026-07-05
from SEC EDGAR full-text search (efts.sec.gov, q=Apple, forms=13F-HR), trimmed
to the first 5 hits with the full real _source shape. It exercises the pure
`_parse` method so parsing is verified with NO network call.

ClankApp was removed on 2026-07-10 (host api.clankapp.com dead, DNS-unreachable),
so its fixture and parser test are gone. SEC EDGAR is the sole active whale feed.
"""
import json
import os

from whale_signal.adapters import Sec13FAdapter, _flag, _user_agent

_FIX = os.path.join(os.path.dirname(__file__), "fixtures")


def _load(name):
    with open(os.path.join(_FIX, name), encoding="utf-8") as f:
        return json.load(f)


def test_sec_edgar_parse_is_delayed_and_clean():
    # Fixture is a REAL efts.sec.gov capture (q=Apple, forms=13F-HR), 5 hits.
    payload = _load("sec_edgar_13f_sample.json")
    rows = Sec13FAdapter()._parse(payload, "AAPL")
    assert len(rows) == 5
    # CIK noise stripped, all 13F evidence flagged delayed, no position value.
    assert all(r.delayed for r in rows)
    assert all("(CIK" not in r.entity for r in rows)
    assert all(r.direction == "long" and r.value_usd == 0.0 for r in rows)
    assert rows[0].entity == "THURSTON, SPRINGER, MILLER, HERD & TITAK, INC."
    assert rows[0].ts.startswith("2024-05-14")


def test_empty_payload_yields_no_rows():
    assert Sec13FAdapter()._parse({"hits": {"hits": []}}, "AAPL") == []


def test_live_disabled_by_default():
    # No opt-in flag -> adapters must not attempt live; fetch returns mock data.
    for var in ("WHALE_LIVE_ENABLED", "SEC_EDGAR_ENABLED"):
        os.environ.pop(var, None)
    assert _flag("WHALE_LIVE_ENABLED") is False
    assert _flag("SEC_EDGAR_ENABLED") is False
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
