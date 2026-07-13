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

from whale_signal.adapters import (SEC_13F_DELAY_LABEL, SEC_FORM4_DELAY_LABEL,
                                    Sec13FAdapter, SecForm4Adapter, _flag,
                                    _user_agent)
from whale_signal.scoring import score_whales

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


def test_sec_edgar_13f_delay_label_surfaces():
    rows = Sec13FAdapter()._parse(_load("sec_edgar_13f_sample.json"), "AAPL")
    assert rows and all(r.delay_label == SEC_13F_DELAY_LABEL for r in rows)
    assert "45 day" in SEC_13F_DELAY_LABEL


def test_sec_edgar_form4_parse_is_delayed_and_labelled():
    # Fixture is a REAL efts.sec.gov capture (q=Apple, forms=4), 5 hits.
    payload = _load("sec_edgar_form4_sample.json")
    rows = SecForm4Adapter()._parse(payload, "AAPL")
    assert rows, "Form 4 fixture must parse to rows"
    assert all(r.source == "sec_form4" for r in rows)
    assert all(r.delayed for r in rows)                 # DELAYED, not live
    assert all("(CIK" not in r.entity for r in rows)    # CIK noise stripped
    assert all(r.value_usd == 0.0 for r in rows)        # FTS exposes no value
    assert all(r.delay_label == SEC_FORM4_DELAY_LABEL for r in rows)
    assert "2 business day" in SEC_FORM4_DELAY_LABEL


def test_form4_empty_payload_yields_no_rows():
    assert SecForm4Adapter()._parse({"hits": {"hits": []}}, "AAPL") == []


def test_form4_rejects_crypto_symbols():
    assert SecForm4Adapter().fetch("BTC/USD") == []


def test_whale_scores_sec_fixtures_within_advisory_bounds():
    # Both SEC forms score into a bounded, advisory signal well under the 0.35
    # position-scale cap (the FTS rows carry no value, so the signal is weak
    # context, never decisive).
    rows = (Sec13FAdapter()._parse(_load("sec_edgar_13f_sample.json"), "AAPL") +
            SecForm4Adapter()._parse(_load("sec_edgar_form4_sample.json"), "AAPL"))
    sig = score_whales(rows, "AAPL", market_bias=0.2)
    assert -1.0 <= sig.whale_bias <= 1.0
    assert 0.0 <= sig.whale_confidence <= 1.0
    assert abs(sig.whale_bias) <= 0.35          # within the advisory whale cap


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
