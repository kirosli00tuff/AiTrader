"""Tests for the multi-LLM consensus advisory service (the "council").

The HTTP layer (``llm_consensus.http_json.post_json``) is always mocked — no
test makes a real network call. An autouse fixture clears the provider API keys
so the baseline is deterministic regardless of the developer's environment.
"""
from dataclasses import dataclass

import pytest
import yaml

from llm_consensus import (
    AnthropicProvider, GateDecision, GeminiProvider, MockLLMProvider,
    ModelVerdict, OpenAIProvider, bias_to_verdict, build_council, build_gate,
    consensus, council_status_line, default_providers, real_providers,
    use_real_council,
)
from llm_consensus import http_json
from llm_consensus.gate import AlwaysProceedGate, HaikuGate

_LLM_KEYS = ("OPENAI_API_KEY", "ANTHROPIC_API_KEY", "GEMINI_API_KEY")


@pytest.fixture(autouse=True)
def _no_llm_keys(monkeypatch):
    """Guarantee no real key leaks in from the environment (no live calls)."""
    for k in _LLM_KEYS:
        monkeypatch.delenv(k, raising=False)


# --- Provider response-envelope builders (per provider) ----------------------

def _openai_env(content: str) -> dict:
    return {"choices": [{"message": {"content": content}}]}


def _anthropic_env(content: str) -> dict:
    return {"content": [{"type": "text", "text": content}]}


def _gemini_env(content: str) -> dict:
    return {"candidates": [{"content": {"parts": [{"text": content}]}}]}


_GOOD_JSON = '{"direction": "long", "confidence": 0.8, "edge": 0.05, "rationale": "up"}'


# --- Test doubles ------------------------------------------------------------

@dataclass
class _StubProvider:
    name: str
    weight: float
    verdict: ModelVerdict

    def score(self, state: dict) -> ModelVerdict:
        return self.verdict


class _ExplodingProvider:
    name = "boom"
    weight = 1.0

    def score(self, state: dict) -> ModelVerdict:
        raise AssertionError("provider must not run when the gate declines")


class _StubGate:
    def __init__(self, proceed: bool, reason: str = "stub"):
        self._proceed = proceed
        self._reason = reason

    def should_review(self, state: dict) -> GateDecision:
        return GateDecision(self._proceed, self._reason, "stub-gate", "real")


_ALWAYS = AlwaysProceedGate()


def _cfg(tmp_path, *, use_real=False, gate=True, name="cfg.yaml") -> str:
    p = tmp_path / name
    p.write_text(yaml.dump({
        "llm_models": {
            "llm_primary": "gpt-5.5",
            "llm_secondary": "claude-opus-4-8",
            "llm_tertiary": "gemini-3.1-pro-preview",
            "llm_gate": "claude-haiku-4-5",
        },
        "llm": {"use_real_council": use_real, "gate_enabled": gate},
        "model_weights": {
            "llm_primary_weight": 0.27,
            "llm_secondary_weight": 0.18,
            "llm_tertiary_weight": 0.12,
        },
    }))
    return str(p)


# --- Original behaviour (must remain unchanged) ------------------------------

def test_bias_to_verdict_buckets():
    assert bias_to_verdict(0.9) == "strong_buy"
    assert bias_to_verdict(-0.9) == "strong_sell"
    assert bias_to_verdict(0.0) in {"hold", "neutral"}


def test_consensus_is_deterministic():
    state = {"symbol": "BTC-USD", "ret_5": 0.02, "imbalance": 0.3, "catalyst": 0.4}
    a = consensus(state).to_dict()
    b = consensus(state).to_dict()
    assert a == b


def test_consensus_output_shape_and_ranges():
    state = {"symbol": "AAPL", "ret_5": 0.01, "imbalance": 0.1, "catalyst": 0.2}
    res = consensus(state)
    d = res.to_dict()
    for key in ("bias", "confidence", "edge", "verdict", "agreement_count", "per_model"):
        assert key in d
    assert -1.0 <= d["bias"] <= 1.0
    assert 0.0 <= d["confidence"] <= 1.0
    assert d["edge"] >= 0.0
    assert len(d["per_model"]) == 3


def test_agreement_count_bounds():
    state = {"symbol": "X", "ret_5": 0.05, "imbalance": 0.5, "catalyst": 0.5}
    res = consensus(state)
    assert 0 <= res.agreement_count <= len(res.per_model)


def test_strong_bull_state_leans_buy():
    bull = {"symbol": "BTC-USD", "ret_5": 0.08, "imbalance": 0.8, "catalyst": 0.9}
    res = consensus(bull)
    assert res.bias > 0
    assert res.verdict in {"buy", "strong_buy"}


def test_custom_providers_respected():
    state = {"symbol": "Z", "ret_5": 0.0}
    providers = [MockLLMProvider(name="only", weight=1.0, skew=0.5)]
    res = consensus(state, providers=providers)
    assert len(res.per_model) == 1
    assert res.per_model[0].model == "only"


def test_default_providers_named_for_cpp_factors():
    names = {p.name for p in default_providers()}
    assert {"llm_primary", "llm_secondary", "llm_tertiary"} <= names


# --- Ensemble math unchanged (locked to the exact weighted formula) ----------

def test_ensemble_math_unchanged():
    state = {"symbol": "AAA"}
    v1 = ModelVerdict("a", 0.8, 0.9, 0.05, "strong_buy", source="real")
    v2 = ModelVerdict("b", 0.4, 0.6, 0.03, "buy", source="real")
    v3 = ModelVerdict("c", -0.2, 0.5, 0.01, "sell", source="real")
    provs = [_StubProvider("a", 0.27, v1), _StubProvider("b", 0.18, v2),
             _StubProvider("c", 0.12, v3)]
    res = consensus(state, providers=provs, gate=_ALWAYS)

    wsum = 0.27 + 0.18 + 0.12
    assert res.bias == pytest.approx((0.8 * 0.27 + 0.4 * 0.18 - 0.2 * 0.12) / wsum)
    assert res.confidence == pytest.approx((0.9 * 0.27 + 0.6 * 0.18 + 0.5 * 0.12) / wsum)
    assert res.edge == pytest.approx((0.05 * 0.27 + 0.03 * 0.18 + 0.01 * 0.12) / wsum)
    # net bias is positive -> two of three providers agree (a, b).
    assert res.agreement_count == 2
    assert len(res.per_model) == 3


# --- Missing key -> clearly-labelled mock (never raises) ---------------------

@pytest.mark.parametrize("provider_cls,env,mid", [
    (OpenAIProvider, "OPENAI_API_KEY", "gpt-5.5"),
    (AnthropicProvider, "ANTHROPIC_API_KEY", "claude-opus-4-8"),
    (GeminiProvider, "GEMINI_API_KEY", "gemini-3.1-pro-preview"),
])
def test_missing_key_returns_labeled_mock(provider_cls, env, mid):
    p = provider_cls(name="slot", weight=0.2, model_id=mid)
    v = p.score({"symbol": "BTC-USD", "ret_5": 0.03})
    assert v.source == "mock"
    assert "MOCK" in v.rationale and env in v.rationale
    assert -1.0 <= v.bias <= 1.0
    assert v.model_id == mid


def test_missing_keys_council_runs_offline_deterministic(tmp_path):
    """Even with use_real_council=true, absent keys -> all-mock, still runs."""
    cfg = _cfg(tmp_path, use_real=True, gate=True)
    state = {"symbol": "ETH-USD", "ret_5": 0.02, "imbalance": 0.2, "catalyst": 0.3}
    a = consensus(state, cfg_path=cfg)
    b = consensus(state, cfg_path=cfg)
    assert a.to_dict() == b.to_dict()
    assert [v.source for v in a.per_model] == ["mock", "mock", "mock"]


# --- Real success path (HTTP mocked) ----------------------------------------

@pytest.mark.parametrize("provider_cls,env,builder", [
    (OpenAIProvider, "OPENAI_API_KEY", _openai_env),
    (AnthropicProvider, "ANTHROPIC_API_KEY", _anthropic_env),
    (GeminiProvider, "GEMINI_API_KEY", _gemini_env),
])
def test_provider_success_parses_real_verdict(provider_cls, env, builder,
                                              monkeypatch):
    monkeypatch.setenv(env, "test-key")
    monkeypatch.setattr(http_json, "post_json",
                        lambda *a, **k: builder(_GOOD_JSON))
    p = provider_cls(name="slot", weight=0.2, model_id="m")
    v = p.score({"symbol": "BTC-USD", "ret_5": 0.03})
    assert v.source == "real"
    assert v.bias == pytest.approx(0.8)  # long * confidence 0.8
    assert v.confidence == pytest.approx(0.8)
    assert v.edge == pytest.approx(0.05)
    assert v.verdict in {"buy", "strong_buy"}


# --- JSON parse failure / call error -> flat --------------------------------

def test_json_parse_failure_falls_back_to_flat(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    monkeypatch.setattr(http_json, "post_json",
                        lambda *a, **k: _openai_env("this is not json at all"))
    p = OpenAIProvider(name="slot", weight=0.2, model_id="gpt-5.5")
    v = p.score({"symbol": "BTC-USD", "ret_5": 0.03})
    assert v.source == "error"
    assert v.bias == 0.0 and v.confidence == 0.0 and v.edge == 0.0
    assert v.verdict == bias_to_verdict(0.0)


def test_call_error_falls_back_to_flat(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")

    def _boom(*a, **k):
        raise http_json.LLMHTTPError("HTTP 500: upstream down")

    monkeypatch.setattr(http_json, "post_json", _boom)
    p = AnthropicProvider(name="slot", weight=0.2, model_id="claude-opus-4-8")
    v = p.score({"symbol": "BTC-USD", "ret_5": 0.03})
    assert v.source == "error"
    assert v.bias == 0.0 and v.confidence == 0.0


def test_provider_exception_never_crashes_council(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")

    def _raise(*a, **k):
        raise RuntimeError("x")

    monkeypatch.setattr(http_json, "post_json", _raise)
    # A raising provider must be swallowed into a flat verdict, not propagate.
    res = consensus({"symbol": "BTC-USD", "ret_5": 0.03},
                    providers=[GeminiProvider(name="slot", weight=1.0,
                                              model_id="gemini-3.1-pro-preview")],
                    gate=_ALWAYS)
    assert res.per_model[0].source == "error"
    assert res.bias == 0.0


# --- Gate behaviour ----------------------------------------------------------

def test_gate_says_no_skips_council():
    res = consensus({"symbol": "BTC-USD", "ret_5": 0.03},
                    providers=[_ExplodingProvider()],  # must NOT be called
                    gate=_StubGate(False, "low signal"))
    assert res.per_model == []
    assert res.bias == 0.0 and res.confidence == 0.0 and res.edge == 0.0
    assert res.agreement_count == 0
    assert res.verdict == bias_to_verdict(0.0)
    assert res.gate == {"proceed": False, "reason": "low signal",
                        "model": "stub-gate", "source": "real"}


def test_gate_says_yes_runs_council():
    state = {"symbol": "BTC-USD", "ret_5": 0.05, "imbalance": 0.4, "catalyst": 0.5}
    res = consensus(state, providers=default_providers(),
                    gate=_StubGate(True, "worth it"))
    assert len(res.per_model) == 3
    assert res.gate["proceed"] is True


def test_gate_disabled_via_config_uses_always_proceed(tmp_path):
    cfg = _cfg(tmp_path, use_real=False, gate=False)
    g = build_gate(cfg_path=cfg)
    assert isinstance(g, AlwaysProceedGate)
    d = g.should_review({"symbol": "X"})
    assert d.proceed is True and d.source == "disabled"


def test_gate_enabled_builds_haiku_gate(tmp_path):
    cfg = _cfg(tmp_path, use_real=False, gate=True)
    g = build_gate(cfg_path=cfg)
    assert isinstance(g, HaikuGate)
    assert g.model_id == "claude-haiku-4-5"


def test_haiku_gate_without_key_is_permissive_mock():
    d = HaikuGate().should_review({"symbol": "X"})
    assert d.proceed is True and d.source == "mock"


def test_haiku_gate_says_no_when_model_declines(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    monkeypatch.setattr(http_json, "post_json", lambda *a, **k: _anthropic_env(
        '{"proceed": false, "reason": "flat range"}'))
    d = HaikuGate().should_review({"symbol": "X"})
    assert d.proceed is False and d.source == "real"
    assert d.reason == "flat range"


def test_haiku_gate_error_is_fail_open(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")

    def _raise(*a, **k):
        raise RuntimeError("net")

    monkeypatch.setattr(http_json, "post_json", _raise)
    d = HaikuGate().should_review({"symbol": "X"})
    assert d.proceed is True and d.source == "error"


# --- Real-vs-mock council selection + startup line ---------------------------

def test_use_real_council_flag_selects_providers(tmp_path):
    real_cfg = _cfg(tmp_path, use_real=True, name="real.yaml")
    mock_cfg = _cfg(tmp_path, use_real=False, name="mock.yaml")

    assert use_real_council(cfg_path=real_cfg) is True
    assert use_real_council(cfg_path=mock_cfg) is False

    rp = build_council(cfg_path=real_cfg)
    assert [type(p).__name__ for p in rp] == [
        "OpenAIProvider", "AnthropicProvider", "GeminiProvider"]
    mp = build_council(cfg_path=mock_cfg)
    assert all(isinstance(p, MockLLMProvider) for p in mp)


def test_real_providers_mapping_and_models():
    provs = {type(p).__name__: p for p in real_providers()}
    assert provs["OpenAIProvider"].model_id == "gpt-5.5"
    assert provs["AnthropicProvider"].model_id == "claude-opus-4-8"
    assert provs["GeminiProvider"].model_id == "gemini-3.1-pro-preview"


def test_status_line_reflects_config(tmp_path):
    real_line = council_status_line(cfg_path=_cfg(tmp_path, use_real=True,
                                                  name="r.yaml"))
    mock_line = council_status_line(cfg_path=_cfg(tmp_path, use_real=False,
                                                  name="m.yaml"))
    assert "REAL council" in real_line and "gpt-5.5" in real_line
    assert "MOCK council" in mock_line
    assert "claude-haiku-4-5" in real_line  # gate on by default


# --- JSON extraction helper --------------------------------------------------

def test_extract_json_object_handles_prose_and_garbage():
    assert http_json.extract_json_object('{"a": 1}') == {"a": 1}
    fenced = 'Sure!\n```json\n{"direction": "short", "confidence": 0.5}\n```\n'
    assert http_json.extract_json_object(fenced) == {
        "direction": "short", "confidence": 0.5}
    assert http_json.extract_json_object("no json here") is None
    assert http_json.extract_json_object("") is None


# --- Timeout / slow-provider resilience (bridge-call timeout fix) -------------

def test_council_timeouts_read_from_config(tmp_path):
    """Task 2: the provider and gate timeouts are config values, not literals,
    and flow into the real providers and the gate."""
    from llm_consensus import config_access
    # The packaged defaults are the fix's values (30s provider, 15s gate).
    assert config_access.provider_timeout_seconds() == 30.0
    assert config_access.gate_timeout_seconds() == 15.0
    # A config override flows through to the built providers and gate.
    cfg = tmp_path / "cfg.yaml"
    cfg.write_text(yaml.dump({"council": {"provider_timeout_seconds": 42,
                                          "gate_timeout_seconds": 7},
                              "llm": {"use_real_council": True, "gate_enabled": True}}))
    p = str(cfg)
    assert config_access.provider_timeout_seconds(p) == 42.0
    assert config_access.gate_timeout_seconds(p) == 7.0
    assert all(getattr(x, "timeout", None) == 42.0 for x in real_providers(p))
    assert getattr(build_gate(p), "timeout", None) == 7.0


def test_slow_provider_times_out_council_proceeds_on_rest(monkeypatch):
    """Task 4: one provider that times out fails ALONE (flat/error verdict); the
    other two answer and the council still produces a verdict. The at-least-one-
    provider rule holds. No real network: the HTTP layer is mocked."""
    for k in _LLM_KEYS:
        monkeypatch.setenv(k, "test-key")

    def _post(url, headers, payload, timeout=None):
        if "generativelanguage" in url:          # Gemini -> simulate a timeout
            raise http_json.LLMHTTPError("request failed: read timed out")
        if "openai" in url:
            return _openai_env(_GOOD_JSON)
        return _anthropic_env(_GOOD_JSON)

    monkeypatch.setattr(http_json, "post_json", _post)
    res = consensus({"symbol": "BTC/USD", "ret_5": 0.03},
                    providers=real_providers(), gate=_ALWAYS)
    # Slot order is primary(OpenAI), secondary(Anthropic), tertiary(Gemini).
    assert res.per_model[0].source == "real"     # answered
    assert res.per_model[1].source == "real"     # answered
    assert res.per_model[2].source == "error"    # timed out, failed alone
    # At least one provider answered, so the council still produced a verdict.
    assert any(v.source == "real" for v in res.per_model)
    assert res.confidence > 0.0


def test_council_is_concurrent_not_serialized(monkeypatch):
    """Task 4: providers are scored concurrently, so a slow provider only delays
    the council by its own time, not the sum of all three. Two providers each
    'sleep' 0.3s; a serial council would take >=0.6s, a concurrent one ~0.3s."""
    import time
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")

    def _post(url, headers, payload, timeout=None):
        time.sleep(0.3)
        if "openai" in url:
            return _openai_env(_GOOD_JSON)
        if "anthropic" in url:
            return _anthropic_env(_GOOD_JSON)
        return _gemini_env(_GOOD_JSON)

    monkeypatch.setattr(http_json, "post_json", _post)
    t0 = time.perf_counter()
    res = consensus({"symbol": "BTC/USD", "ret_5": 0.03},
                    providers=real_providers(), gate=_ALWAYS)
    elapsed = time.perf_counter() - t0
    assert len(res.per_model) == 3
    assert elapsed < 0.75          # concurrent (~0.3s), not serial (~0.9s)
