"""Tests for the research_satellite deep-research path and its cost controls.

The research path produces a STRUCTURED thesis (direction, conviction, horizon,
rationale) from the gate-screened council. Cost is bounded by research_daily_budget
and the combined monthly spend ceiling (the C++ engine enforces both; these tests
lock the Python surface). No test makes a real network call: with no provider keys
the council degrades to deterministic mock verdicts, so nothing binds or leaks.
"""
from __future__ import annotations

import pytest

from research_satellite import research_thesis
from llm_consensus import config_access as ca

_LLM_KEYS = ("OPENAI_API_KEY", "ANTHROPIC_API_KEY", "GEMINI_API_KEY")


@pytest.fixture(autouse=True)
def _no_llm_keys(monkeypatch):
    # Force the offline mock council (deterministic, no network).
    for k in _LLM_KEYS:
        monkeypatch.delenv(k, raising=False)


def _write_cfg(tmp_path, body: str) -> str:
    p = tmp_path / "cfg.yaml"
    p.write_text(body)
    return str(p)


def test_research_thesis_is_structured():
    t = research_thesis({"symbol": "BTC/USD", "category": "crypto", "bias": 0.6})
    # Structured long-term thesis fields.
    assert t["symbol"] == "BTC/USD"
    assert t["direction"] in ("long", "short", "flat")
    assert 0.0 <= t["conviction"] <= 1.0
    assert t["horizon"] in ("weeks", "months", "unknown")
    assert isinstance(t["rationale"], str) and t["rationale"]
    assert "conviction_threshold" in t


def test_research_thesis_never_raises_and_no_key_in_output():
    t = research_thesis({"symbol": "SPY"})
    # The thesis text must never contain a credential-shaped value.
    blob = " ".join(str(v) for v in t.values())
    assert "sk-" not in blob and "OPENAI_API_KEY" not in blob


def test_conviction_threshold_gates_entry(tmp_path):
    cfg = _write_cfg(tmp_path, "sleeves:\n  research_conviction_threshold: 0.85\n")
    assert ca.research_conviction_threshold(cfg) == 0.85
    t = research_thesis({"symbol": "QQQ"}, cfg_path=cfg)
    # The thesis echoes the threshold the engine applies before opening a position.
    assert t["conviction_threshold"] == 0.85


def test_research_disabled_by_default(tmp_path):
    cfg = _write_cfg(tmp_path, "sleeves:\n  quant_core_enabled: true\n")
    assert ca.research_satellite_enabled(cfg) is False
    assert ca.research_daily_budget(cfg) == 6


def test_combined_spend_ceiling_pauses_both_sleeves(tmp_path):
    cfg = _write_cfg(
        tmp_path,
        "sleeves:\n"
        "  combined_monthly_spend_ceiling_usd: 10.0\n"
        "  research_est_cost_per_call_usd: 1.0\n",
    )
    # council est cost defaults 0.04; research 1.0 here. 6 research calls = $6,
    # not over $10; add council spend to cross it.
    assert not ca.combined_spend_ceiling_reached(0, 6, cfg)      # $6 < $10
    assert ca.combined_spend_ceiling_reached(0, 10, cfg)         # $10 >= $10
    # Council spend counts toward the SAME combined ceiling.
    assert ca.combined_spend_ceiling_reached(100, 6, cfg)        # $6 + $4 = $10


def test_combined_ceiling_disabled_at_zero(tmp_path):
    cfg = _write_cfg(tmp_path, "sleeves:\n  combined_monthly_spend_ceiling_usd: 0.0\n")
    assert not ca.combined_spend_ceiling_reached(10_000, 10_000, cfg)
