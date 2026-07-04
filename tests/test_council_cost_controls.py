"""Tests for the LLM-council cost controls (Task 4).

Covers the Python-owned half of the cost controls:
  * the ``council:`` config accessors (budget / cooldown / token-cap / skip
    thresholds) with defaults, overrides, and bad-value fallback;
  * the per-provider response token cap wired into every real request payload;
  * the base-check gate skipping the (expensive) council and surfacing the skip
    reason the engine logs as a ``council_skip`` event.

Budget/cooldown *enforcement* lives in the C++ engine (``council_gate.cpp``,
exercised by ``tests/test_strategy.cpp``); here we lock the config surface those
knobs are read from plus the token cap the Python side applies per call. No test
makes a real network call — ``http_json.post_json`` is always mocked.
"""
from dataclasses import dataclass

import pytest

from llm_consensus import (
    AnthropicProvider, GeminiProvider, GateDecision, OpenAIProvider,
    consensus, real_providers,
)
from llm_consensus import http_json
from llm_consensus.config_access import (
    council_daily_budget, council_max_tokens, council_min_agreement,
    council_min_confidence, neutral_skip_strength_threshold,
    per_symbol_council_cooldown_minutes,
)

_LLM_KEYS = ("OPENAI_API_KEY", "ANTHROPIC_API_KEY", "GEMINI_API_KEY")


@pytest.fixture(autouse=True)
def _no_llm_keys(monkeypatch):
    for k in _LLM_KEYS:
        monkeypatch.delenv(k, raising=False)


def _write_cfg(tmp_path, body: str, name: str = "cfg.yaml") -> str:
    p = tmp_path / name
    p.write_text(body)
    return str(p)


# --- Config accessors: defaults --------------------------------------------

def test_cost_control_defaults_when_no_council_block(tmp_path):
    cfg = _write_cfg(tmp_path, "llm:\n  use_real_council: false\n", "none.yaml")
    assert council_max_tokens(cfg) == 400
    assert council_daily_budget(cfg) == 30
    assert per_symbol_council_cooldown_minutes(cfg) == 60
    assert council_min_confidence(cfg) == pytest.approx(0.6)
    assert council_min_agreement(cfg) == 2
    assert neutral_skip_strength_threshold(cfg) == pytest.approx(0.5)


def test_missing_config_file_falls_back_to_defaults(tmp_path):
    missing = str(tmp_path / "does_not_exist.yaml")
    assert council_max_tokens(missing) == 400
    assert council_daily_budget(missing) == 30


# --- Config accessors: overrides -------------------------------------------

def test_council_block_overrides_are_read(tmp_path):
    cfg = _write_cfg(tmp_path, (
        "council:\n"
        "  council_daily_budget: 12\n"
        "  per_symbol_council_cooldown_minutes: 90\n"
        "  council_max_tokens: 256\n"
        "  council_min_confidence: 0.75\n"
        "  council_min_agreement: 3\n"
        "  neutral_skip_strength_threshold: 0.4\n"
    ), "over.yaml")
    assert council_daily_budget(cfg) == 12
    assert per_symbol_council_cooldown_minutes(cfg) == 90
    assert council_max_tokens(cfg) == 256
    assert council_min_confidence(cfg) == pytest.approx(0.75)
    assert council_min_agreement(cfg) == 3
    assert neutral_skip_strength_threshold(cfg) == pytest.approx(0.4)


def test_bad_values_fall_back_to_defaults(tmp_path):
    cfg = _write_cfg(tmp_path, (
        "council:\n"
        "  council_max_tokens: not-a-number\n"
        "  council_daily_budget: []\n"
    ), "bad.yaml")
    assert council_max_tokens(cfg) == 400
    assert council_daily_budget(cfg) == 30


def test_accessor_return_types(tmp_path):
    cfg = _write_cfg(tmp_path, "council: {}\n", "types.yaml")
    assert isinstance(council_max_tokens(cfg), int)
    assert isinstance(council_daily_budget(cfg), int)
    assert isinstance(per_symbol_council_cooldown_minutes(cfg), int)
    assert isinstance(council_min_agreement(cfg), int)
    assert isinstance(council_min_confidence(cfg), float)
    assert isinstance(neutral_skip_strength_threshold(cfg), float)


# --- Token cap wired into every provider (cost control) --------------------

def test_real_providers_receive_configured_token_cap(tmp_path):
    cfg = _write_cfg(tmp_path, (
        "llm:\n  use_real_council: true\n"
        "council:\n  council_max_tokens: 222\n"
    ), "tok.yaml")
    provs = real_providers(cfg)
    assert provs, "real_providers must return the three slots"
    assert all(p.max_tokens == 222 for p in provs), \
        "every provider must carry the configured token cap"


def _capture_payload(monkeypatch, good_json_response):
    """Patch post_json to record the outgoing payload and return a fixed resp."""
    seen = {}

    def _fake_post(url, headers, payload, timeout=None):
        seen["payload"] = payload
        return good_json_response

    monkeypatch.setattr(http_json, "post_json", _fake_post)
    return seen


_GOOD = '{"direction": "long", "confidence": 0.7, "edge": 0.04, "rationale": "x"}'


def test_openai_payload_carries_token_cap(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    seen = _capture_payload(monkeypatch, {"choices": [
        {"message": {"content": _GOOD}}]})
    p = OpenAIProvider(name="s", weight=0.2, model_id="gpt-5.5", max_tokens=128)
    p.score({"symbol": "BTC-USD", "ret_5": 0.03})
    assert seen["payload"]["max_tokens"] == 128


def test_anthropic_payload_carries_token_cap(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    seen = _capture_payload(monkeypatch, {"content": [
        {"type": "text", "text": _GOOD}]})
    p = AnthropicProvider(name="s", weight=0.2, model_id="claude-opus-4-8",
                          max_tokens=99)
    p.score({"symbol": "BTC-USD", "ret_5": 0.03})
    assert seen["payload"]["max_tokens"] == 99


def test_gemini_payload_carries_token_cap(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")
    seen = _capture_payload(monkeypatch, {"candidates": [
        {"content": {"parts": [{"text": _GOOD}]}}]})
    p = GeminiProvider(name="s", weight=0.2, model_id="gemini-3.1-pro",
                       max_tokens=64)
    p.score({"symbol": "BTC-USD", "ret_5": 0.03})
    assert seen["payload"]["generationConfig"]["maxOutputTokens"] == 64


# --- Gate skip = cost control: don't pay for the council -------------------

@dataclass
class _DeclineGate:
    reason: str = "neutral regime + weak signal"

    def should_review(self, state: dict) -> GateDecision:
        return GateDecision(False, self.reason, "gemini-3-flash", "real")


class _MustNotRunProvider:
    name = "expensive"
    weight = 1.0

    def score(self, state: dict):
        raise AssertionError("council must be skipped when the gate declines")


def test_gate_skip_avoids_council_and_logs_reason():
    res = consensus({"symbol": "BTC-USD", "ret_5": 0.01},
                    providers=[_MustNotRunProvider()],
                    gate=_DeclineGate("cooldown active"))
    # No provider ran (no cost incurred) and the result is flat.
    assert res.per_model == []
    assert res.bias == 0.0 and res.confidence == 0.0 and res.edge == 0.0
    # The skip reason is carried out for the engine to log as council_skip.
    assert res.gate["proceed"] is False
    assert res.gate["reason"] == "cooldown active"
    assert res.gate["model"] == "gemini-3-flash"
