"""A billing 429 is permanent, latches, and is visible.

The 2026-07-27 wide council run retried every quota-exceeded 429 as though it
were a rate limit: GPT-5.5 failed 315 of 389 calls from 03:30 and Gemini 73
from 08:16, and each failure was made twice. These tests pin the distinction
the retry policy was missing, the latch that stops calling a dry account, the
disjoint accounting that keeps exhaustion separate from an error and from an
abstention, and the operator surfaces that make a one-handed council visible.

The real provider error shapes are used verbatim, because the defect was that
the classifier could not see the field that separates the two meanings.
"""
from __future__ import annotations

import json
import sqlite3

import pytest

from llm_consensus import provider_health as ph
from llm_consensus.http_json import LLMHTTPError


@pytest.fixture(autouse=True)
def _clean_latch():
    """The latch is process state, so every test starts and ends with it clear."""
    ph.reset_exhaustion()
    yield
    ph.reset_exhaustion()


# --- The real error shapes, as each provider actually sends them -------------

def _openai_quota() -> LLMHTTPError:
    body = {"error": {
        "message": ("You exceeded your current quota, please check your plan "
                    "and billing details."),
        "type": "insufficient_quota", "param": None,
        "code": "insufficient_quota"}}
    return LLMHTTPError(f"HTTP 429: {json.dumps(body)[:200]}", status=429,
                        body=body, text=json.dumps(body))


def _openai_rate_limit() -> LLMHTTPError:
    body = {"error": {"message": "Rate limit reached for gpt-5.5",
                      "type": "rate_limit_exceeded", "param": None,
                      "code": "rate_limit_exceeded"}}
    return LLMHTTPError(f"HTTP 429: {json.dumps(body)[:200]}", status=429,
                        body=body, text=json.dumps(body))


def _anthropic_credit() -> LLMHTTPError:
    """Anthropic reports credit exhaustion as a 400, never a 429."""
    body = {"type": "error", "error": {
        "type": "invalid_request_error",
        "message": ("Your credit balance is too low to access the Anthropic "
                    "API. Please go to Plans & Billing to upgrade or purchase "
                    "credits.")}}
    return LLMHTTPError(f"HTTP 400: {json.dumps(body)[:200]}", status=400,
                        body=body, text=json.dumps(body))


def _anthropic_rate_limit() -> LLMHTTPError:
    body = {"type": "error", "error": {
        "type": "rate_limit_error",
        "message": "Number of requests has exceeded your rate limit"}}
    return LLMHTTPError(f"HTTP 429: {json.dumps(body)[:200]}", status=429,
                        body=body, text=json.dumps(body))


def _gemini_quota() -> LLMHTTPError:
    body = {"error": {"code": 429, "status": "RESOURCE_EXHAUSTED",
                      "message": ("You exceeded your current quota, please "
                                  "check your plan and billing details.")}}
    return LLMHTTPError(f"HTTP 429: {json.dumps(body)[:200]}", status=429,
                        body=body, text=json.dumps(body))


def _gemini_per_minute() -> LLMHTTPError:
    """Gemini answers RESOURCE_EXHAUSTED for a rate limit too, which is why it
    cannot be classified from its status and defaults to not retrying."""
    body = {"error": {"code": 429, "status": "RESOURCE_EXHAUSTED",
                      "message": ("Quota exceeded for quota metric "
                                  "'Generate requests', limit 60 per minute")}}
    return LLMHTTPError(f"HTTP 429: {json.dumps(body)[:200]}", status=429,
                        body=body, text=json.dumps(body))


# --- Task 1: the two meanings of a 429 are separated ------------------------

def test_a_billing_429_is_classified_exhausted_not_transient():
    assert ph.classify(_openai_quota(), label="OpenAI") == ph.EXHAUSTED
    assert ph.classify(_gemini_quota(), label="Gemini") == ph.EXHAUSTED


def test_a_rate_limit_429_stays_transient():
    assert ph.classify(_openai_rate_limit(), label="OpenAI") == ph.TRANSIENT
    assert ph.classify(_anthropic_rate_limit(), label="Anthropic") == ph.TRANSIENT


def test_anthropic_credit_exhaustion_is_caught_even_though_it_is_a_400():
    """Keying exhaustion off the status code is the original mistake."""
    assert ph.classify(_anthropic_credit(), label="Anthropic") == ph.EXHAUSTED


def test_gemini_429_is_never_retried_because_it_cannot_be_distinguished():
    """The safe default where a provider does not separate the two meanings."""
    assert ph.classify(_gemini_per_minute(), label="Gemini") != ph.TRANSIENT
    # ...and it does not latch, because dropping a healthy provider for a
    # per-minute limit costs more than the one retry it saves.
    assert ph.classify(_gemini_per_minute(), label="Gemini") == ph.NO_RETRY


def test_the_same_429_from_a_distinguishing_provider_is_still_retried():
    """The ambiguity rule is per provider, not a blanket ban on retrying 429."""
    assert ph.classify(_openai_rate_limit(), label="OpenAI") == ph.TRANSIENT


def test_a_transport_failure_is_still_transient():
    exc = LLMHTTPError("request failed: Read timed out. (read timeout=30.0)")
    assert ph.classify(exc, label="Gemini") == ph.TRANSIENT


# --- Task 1/2: the retry policy honours the classification ------------------

def _provider(monkeypatch, raises, timeout=30.0):
    from llm_consensus import http_json
    from llm_consensus.providers import OpenAIProvider
    calls = {"n": 0}

    def fail(url, headers, payload, timeout=30.0):
        calls["n"] += 1
        raise raises()

    monkeypatch.setattr(http_json, "post_json", fail)
    monkeypatch.setattr("llm_consensus.providers.PROVIDER_RETRY_BACKOFF_SECONDS",
                        0.01)
    p = OpenAIProvider(name="llm_primary", model_id="gpt-5.5", timeout=timeout)
    monkeypatch.setattr(p, "_api_key", lambda: "test-key")
    monkeypatch.setattr(p, "_request", lambda state, key: ("http://x", {}, {}))
    monkeypatch.setattr(p, "_text_from_response", json.dumps)
    return p, calls


def test_a_rate_limit_429_is_retried_exactly_once(monkeypatch):
    p, calls = _provider(monkeypatch, _openai_rate_limit)
    v = p.score({"symbol": "BTC/USD"})
    assert calls["n"] == 2, "a rate limit is worth one more attempt"
    assert v.source == "error"


def test_a_billing_429_is_never_retried(monkeypatch):
    """THE DEFECT. This call was made twice, 315 times over, for nothing."""
    p, calls = _provider(monkeypatch, _openai_quota)
    v = p.score({"symbol": "BTC/USD"})
    assert calls["n"] == 1, "an exhausted account cannot answer a second time"
    assert v.source == "exhausted"


# --- Task 2: exhaustion latches for the session -----------------------------

def test_exhaustion_latches_and_no_further_call_is_made(monkeypatch):
    p, calls = _provider(monkeypatch, _openai_quota)
    p.score({"symbol": "BTC/USD"})
    assert calls["n"] == 1
    for _ in range(5):
        v = p.score({"symbol": "ETH/USD"})
        assert v.source == "exhausted"
    assert calls["n"] == 1, "the provider is not contacted again this session"


def test_the_latch_is_keyed_on_the_account_not_the_model(monkeypatch):
    """The quota belongs to the API key, so every model behind it is dry."""
    p, calls = _provider(monkeypatch, _openai_quota)
    p.score({"symbol": "BTC/USD"})
    assert ph.is_exhausted("OpenAI") and ph.is_exhausted("openai")
    assert not ph.is_exhausted("Anthropic"), "one dry key is not all of them"


def test_a_latched_verdict_carries_no_attempt_and_stays_non_directional(
        monkeypatch):
    p, _ = _provider(monkeypatch, _openai_quota)
    p.score({"symbol": "BTC/USD"})
    v = p.score({"symbol": "ETH/USD"})
    assert v.extra.get("attempts") == 0, "no call was made at all"
    assert v.bias == 0.0, "an unasked provider contributes no direction"
    assert v.extra.get("exhausted_since"), "when it went dry is recorded"


# --- Task 2: recorded distinctly from an error and from an abstention -------

def _mixed_verdicts():
    from llm_consensus.verdicts import ModelVerdict, flat_verdict
    return [
        ModelVerdict(model="llm_primary", bias=0.6, confidence=0.6, edge=0.02,
                     verdict="buy", source="real", model_id="gpt-5.5"),
        ModelVerdict(model="llm_secondary", bias=0.0, confidence=0.55, edge=0.0,
                     verdict="hold", source="real", model_id="claude-opus-4-8"),
        flat_verdict("llm_tertiary", "flat: call error", source="error",
                     model_id="gemini-3.1-pro-preview"),
        flat_verdict("llm_quaternary", "flat: exhausted", source="exhausted",
                     model_id="gpt-5.5"),
    ]


def _always_gate():
    from llm_consensus.gate import AlwaysProceedGate
    return AlwaysProceedGate(reason="test", source="test")


class _Stub:
    def __init__(self, v):
        self.name, self.weight, self._v = v.model, 0.2, v

    def score(self, state):
        return self._v


def test_the_three_non_directional_outcomes_are_disjoint():
    from llm_consensus.verdicts import is_error, is_exhausted
    v = _mixed_verdicts()
    assert is_exhausted(v[3]) and not is_exhausted(v[2])
    # is_error covers every non-answer so the abstention subtraction is honest,
    # and is_exhausted is what separates the two kinds of non-answer.
    assert is_error(v[2]) and is_error(v[3])
    assert not is_error(v[1]), "a considered hold is not a failure"


def test_the_composed_result_counts_them_separately():
    from llm_consensus.consensus import consensus
    r = consensus({"symbol": "BTC/USD"},
                  providers=[_Stub(v) for v in _mixed_verdicts()],
                  gate=_always_gate())
    assert r.directional_count == 1
    assert r.abstentions == 1, "only the provider that answered and held"
    assert r.errors == 1, "the failed call, and not the dry account"
    assert r.exhausted == 1, "the dry account, counted on its own"
    total = r.directional_count + r.abstentions + r.errors + r.exhausted
    assert total == 4, "every provider lands in exactly one bucket"


def test_exhaustion_is_persisted_distinctly(tmp_path):
    from llm_consensus.consensus import consensus
    from llm_consensus.persist import load_evaluation
    db = str(tmp_path / "council.db")
    # Evidence that clears the pre-call minimum, so the round actually scores
    # providers rather than short-circuiting into a refusal.
    evidence = {"closes_5min": [1.0] * 12,
                "closes_5min_last_ts": "2026-07-27T19:00:00Z"}
    consensus({"symbol": "BTC/USD", "db": db, "_evidence": evidence,
               "price": 1.0},
              providers=[_Stub(v) for v in _mixed_verdicts()],
              gate=_always_gate())
    conn = sqlite3.connect(db)
    rows = conn.execute(
        "SELECT slot, abstained, errored, exhausted FROM council_eval_provider "
        "ORDER BY id").fetchall()
    ev = conn.execute("SELECT errors, exhausted FROM council_eval").fetchone()
    conn.close()
    flags = {r[0]: (r[1], r[2], r[3]) for r in rows}
    assert flags["llm_secondary"] == (1, 0, 0), "answered and held"
    assert flags["llm_tertiary"] == (0, 1, 0), "call failed"
    assert flags["llm_quaternary"] == (0, 0, 1), "account is dry"
    assert ev == (1, 1), "the round records one error and one exhaustion"
    stored = load_evaluation(db, 1)
    by_slot = {p["slot"]: p for p in stored["providers"]}
    assert by_slot["llm_quaternary"]["exhausted"] is True
    assert by_slot["llm_quaternary"]["errored"] is False
    assert by_slot["llm_tertiary"]["errored"] is True


# --- Task 2: it surfaces where a human reads it -----------------------------

def test_the_startup_block_names_an_exhausted_provider():
    from llm_consensus.consensus import council_status_line
    assert "EXHAUSTED" not in council_status_line()
    ph.mark_exhausted("OpenAI", model_id="gpt-5.5", detail="quota")
    line = council_status_line()
    assert "EXHAUSTED" in line and "OpenAI" in line and "gpt-5.5" in line
    assert "fewer providers than configured" in line


def test_the_exhaustion_line_is_empty_when_every_account_is_funded():
    assert ph.exhaustion_line() == ""


def test_the_gui_reports_an_exhausted_slot_separately_from_an_errored_one(
        tmp_path, monkeypatch):
    """The operator surface must not read a dry account as a failed call."""
    from api_server import operator, store
    db = str(tmp_path / "gui.db")
    conn = sqlite3.connect(db)
    conn.execute("CREATE TABLE council_eval (id INTEGER PRIMARY KEY, ts TEXT, "
                 "symbol TEXT, directional_count INT, abstentions INT, "
                 "errors INT, exhausted INT)")
    conn.execute("CREATE TABLE council_eval_provider (id INTEGER PRIMARY KEY, "
                 "eval_id INT, slot TEXT, source TEXT, errored INT, "
                 "exhausted INT)")
    conn.execute("INSERT INTO council_eval VALUES (1,'2026-07-27T19:00:00Z',"
                 "'BTC/USD',1,0,1,1)")
    conn.execute("INSERT INTO council_eval_provider VALUES "
                 "(1,1,'llm_secondary','error',1,0)")
    conn.execute("INSERT INTO council_eval_provider VALUES "
                 "(2,1,'llm_tertiary','exhausted',0,1)")
    conn.commit()
    conn.close()
    monkeypatch.setattr(store, "DB_PATH", db, raising=False)
    monkeypatch.setattr(store, "_db_path", lambda: db, raising=False)
    slots, nums = operator._council_error_facts("BTC/USD",
                                                "2026-07-27T19:00:30Z")
    assert "llm_tertiary" in slots, "a dry account is a failed slot"
    assert nums.get("exhausted_slots") == ["llm_tertiary"]
    assert "llm_secondary" not in nums.get("exhausted_slots", [])


def test_exhausted_providers_are_enumerable_for_a_research_report():
    ph.mark_exhausted("Gemini", model_id="gemini-3.1-pro-preview",
                      detail="quota")
    latched = ph.exhausted_providers()
    assert set(latched) == {"gemini"}
    assert latched["gemini"]["model_id"] == "gemini-3.1-pro-preview"
    assert latched["gemini"]["since"].endswith("Z")


def test_the_first_diagnosis_wins_and_marking_twice_is_idempotent():
    ph.mark_exhausted("OpenAI", model_id="gpt-5.5", detail="first cause")
    ph.mark_exhausted("OpenAI", model_id="gpt-5.5", detail="later cause")
    assert ph.exhausted_providers()["openai"]["detail"] == "first cause"
