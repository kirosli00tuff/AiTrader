"""Tests for the non-fatal startup model-reachability check.

All provider responses are mocked; there are NO real network calls. The tests
prove: each provider list shape parses, an unreachable configured model warns
(without raising), an absent key or unavailable list is unchecked (no false
alarm), a `-preview` word suffix is NOT treated as a date alias, and no key
value ever leaks into a returned record or a warning string.
"""
import pytest
import yaml

from llm_consensus import model_check


def _cfg(tmp_path, models: dict) -> str:
    p = tmp_path / "cfg.yaml"
    p.write_text(yaml.dump({"llm_models": models}))
    return str(p)


# --- _reachable --------------------------------------------------------------

def test_reachable_exact_match():
    assert model_check._reachable("gpt-5.5", {"gpt-5.5", "gpt-4o"})


def test_reachable_date_suffixed_alias():
    ids = {"claude-haiku-4-5-20251001"}
    assert model_check._reachable("claude-haiku-4-5", ids)


def test_word_suffix_is_not_a_date_alias():
    # gemini-3.1-pro must NOT falsely match gemini-3.1-pro-preview.
    ids = {"gemini-3.1-pro-preview"}
    assert model_check._reachable("gemini-3.1-pro-preview", ids)
    assert not model_check._reachable("gemini-3.1-pro", ids)


# --- list_models parses each provider shape ---------------------------------

def test_list_models_parses_each_provider_shape(monkeypatch):
    openai = {"data": [{"id": "gpt-5.5"}, {"id": "gpt-4o"}]}
    anthropic = {"data": [{"id": "claude-opus-4-8"},
                          {"id": "claude-haiku-4-5-20251001"}]}
    gemini = {"models": [
        {"name": "models/gemini-3.1-pro-preview",
         "supportedGenerationMethods": ["generateContent"]},
        {"name": "models/veo-3", "supportedGenerationMethods": ["predict"]}]}

    def fake_get(url, headers):
        if "openai" in url:
            return openai
        if "anthropic" in url:
            return anthropic
        return gemini

    monkeypatch.setattr(model_check, "_get_json", fake_get)
    assert model_check.list_models("openai", "k") == {"gpt-5.5", "gpt-4o"}
    assert model_check.list_models("anthropic", "k") == {
        "claude-opus-4-8", "claude-haiku-4-5-20251001"}
    # Gemini keeps only generateContent-capable models (veo-3 is dropped).
    assert model_check.list_models("gemini", "k") == {"gemini-3.1-pro-preview"}


def test_list_models_returns_none_on_failure(monkeypatch):
    def boom(url, headers):
        raise RuntimeError("network down")

    monkeypatch.setattr(model_check, "_get_json", boom)
    assert model_check.list_models("openai", "k") is None


# --- validate_configured_models ---------------------------------------------

def test_validate_flags_unreachable_and_passes_reachable(tmp_path, monkeypatch):
    cfg = _cfg(tmp_path, {"llm_primary": "gpt-9-does-not-exist",
                          "llm_secondary": "claude-opus-4-8",
                          "llm_tertiary": "gemini-3.1-pro-preview",
                          "llm_gate": "claude-haiku-4-5"})
    monkeypatch.setattr(model_check, "_resolve", lambda env: "KEY-" + env)
    lists = {"openai": {"gpt-5.5"},
             "anthropic": {"claude-opus-4-8", "claude-haiku-4-5-20251001"},
             "gemini": {"gemini-3.1-pro-preview"}}
    monkeypatch.setattr(model_check, "list_models",
                        lambda provider, key: lists[provider])
    res = {r["slot"]: r for r in model_check.validate_configured_models(cfg)}
    assert res["llm_primary"]["status"] == "warning"
    assert res["llm_secondary"]["status"] == "ok"
    assert res["llm_tertiary"]["status"] == "ok"
    assert res["llm_gate"]["status"] == "ok"        # date-suffixed alias


def test_validate_unchecked_when_key_absent(tmp_path, monkeypatch):
    cfg = _cfg(tmp_path, {"llm_primary": "gpt-5.5"})
    monkeypatch.setattr(model_check, "_resolve", lambda env: None)
    monkeypatch.setattr(model_check, "list_models",
                        lambda p, k: pytest.fail("must not fetch without a key"))
    res = model_check.validate_configured_models(cfg)
    assert res[0]["status"] == "unchecked"
    assert "not set" in res[0]["detail"]


def test_validate_unchecked_when_list_unavailable(tmp_path, monkeypatch):
    cfg = _cfg(tmp_path, {"llm_primary": "gpt-5.5"})
    monkeypatch.setattr(model_check, "_resolve", lambda env: "k")
    monkeypatch.setattr(model_check, "list_models", lambda p, k: None)
    res = model_check.validate_configured_models(cfg)
    assert res[0]["status"] == "unchecked"
    assert "unavailable" in res[0]["detail"]


# --- warn_unreachable_models -------------------------------------------------

def test_warn_returns_and_prints(tmp_path, monkeypatch):
    cfg = _cfg(tmp_path, {"llm_tertiary": "gemini-3.1-pro"})   # word suffix
    monkeypatch.setattr(model_check, "_resolve", lambda env: "k")
    monkeypatch.setattr(model_check, "list_models",
                        lambda p, k: {"gemini-3.1-pro-preview"})
    printed: list[str] = []
    warnings = model_check.warn_unreachable_models(cfg, printer=printed.append)
    assert warnings and "gemini-3.1-pro" in warnings[0]
    assert printed and "WARNING" in printed[0]


def test_warn_never_raises(monkeypatch):
    def boom(cfg_path=None):
        raise RuntimeError("boom")

    monkeypatch.setattr(model_check, "validate_configured_models", boom)
    assert model_check.warn_unreachable_models() == []


def test_no_key_value_leaks(tmp_path, monkeypatch):
    cfg = _cfg(tmp_path, {"llm_primary": "gpt-nope",
                          "llm_secondary": "claude-opus-4-8",
                          "llm_tertiary": "gemini-3.1-pro-preview",
                          "llm_gate": "claude-haiku-4-5"})
    # Distinctive sentinel that the resolver "returns"; it must never appear in
    # any record or warning. Deliberately not a key shape so the pre-commit
    # secret scanner does not flag this test.
    sentinel = "DISTINCTIVE-VALUE-MUST-NOT-APPEAR-IN-OUTPUT-0001"
    monkeypatch.setattr(model_check, "_resolve", lambda env: sentinel)
    monkeypatch.setattr(model_check, "list_models", lambda p, k: {
        "gpt-5.5", "claude-opus-4-8", "claude-haiku-4-5-20251001",
        "gemini-3.1-pro-preview"})
    printed: list[str] = []
    warnings = model_check.warn_unreachable_models(cfg, printer=printed.append)
    records = model_check.validate_configured_models(cfg)
    assert warnings, "an unreachable model should produce a warning"
    blob = repr(records) + repr(warnings) + repr(printed)
    assert sentinel not in blob
