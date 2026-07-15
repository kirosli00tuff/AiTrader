"""Tests for the active_quant profile surface and the council spend ceiling.

Covers the Python-owned half of the evidence-backed quant stack (the C++ engine
owns real enforcement, exercised by tests/test_strategy.cpp):
  * the strategy profile getter (swing default, active_quant overlay);
  * the active_quant overlay selecting the full council cost-control set
    (budget, cooldown, spend ceiling, fast-tier thresholds);
  * spend_ceiling_reached forcing the fast tier when a ceiling is reached.

No test makes a network call, and config_access reads config only (no keys,
no sockets), so there is nothing to bind or leak here.
"""
from __future__ import annotations

from llm_consensus import config_access as ca


def _write_cfg(tmp_path, body: str, name: str = "cfg.yaml") -> str:
    p = tmp_path / name
    p.write_text(body)
    return str(p)


def test_default_profile_is_swing(tmp_path):
    cfg = _write_cfg(tmp_path, "strategy:\n  profile: swing\n")
    assert ca.profile(cfg) == "swing"
    # Swing leaves the spend ceilings and fast-tier thresholds disabled.
    assert ca.council_daily_spend_ceiling_usd(cfg) == 0.0
    assert ca.council_monthly_spend_ceiling_usd(cfg) == 0.0
    assert ca.fast_tier_max_notional_pct(cfg) == 0.0
    assert ca.fast_tier_max_conviction(cfg) == 0.0


def test_missing_profile_defaults_to_swing(tmp_path):
    cfg = _write_cfg(tmp_path, "council:\n  council_daily_budget: 30\n")
    assert ca.profile(cfg) == "swing"
    assert ca.council_daily_budget(cfg) == 30


def test_active_quant_overlay_selects_the_full_set(tmp_path):
    body = (
        "strategy:\n"
        "  profile: active_quant\n"
        "council:\n"
        "  council_daily_budget: 30\n"
        "  per_symbol_council_cooldown_minutes: 60\n"
        "active_quant:\n"
        "  council_daily_budget: 40\n"
        "  per_symbol_council_cooldown_minutes: 45\n"
        "  fast_tier_max_notional_pct: 0.01\n"
        "  fast_tier_max_conviction: 0.6\n"
        "  council_daily_spend_ceiling_usd: 5.0\n"
        "  council_monthly_spend_ceiling_usd: 100.0\n"
        "  council_est_cost_per_call_usd: 0.04\n"
    )
    cfg = _write_cfg(tmp_path, body)
    assert ca.profile(cfg) == "active_quant"
    # The active_quant block overrides the council base (mirrors the C++ loader).
    assert ca.council_daily_budget(cfg) == 40
    assert ca.per_symbol_council_cooldown_minutes(cfg) == 45
    assert ca.fast_tier_max_notional_pct(cfg) == 0.01
    assert ca.fast_tier_max_conviction(cfg) == 0.6
    assert ca.council_daily_spend_ceiling_usd(cfg) == 5.0
    assert ca.council_monthly_spend_ceiling_usd(cfg) == 100.0


def test_swing_ignores_the_active_quant_block(tmp_path):
    # An active_quant block present but profile swing must NOT overlay it.
    body = (
        "strategy:\n"
        "  profile: swing\n"
        "council:\n"
        "  council_daily_budget: 30\n"
        "active_quant:\n"
        "  council_daily_budget: 40\n"
        "  council_daily_spend_ceiling_usd: 5.0\n"
    )
    cfg = _write_cfg(tmp_path, body)
    assert ca.council_daily_budget(cfg) == 30
    assert ca.council_daily_spend_ceiling_usd(cfg) == 0.0


def test_spend_ceiling_forces_fast_tier_when_reached(tmp_path):
    body = (
        "strategy:\n"
        "  profile: active_quant\n"
        "active_quant:\n"
        "  council_est_cost_per_call_usd: 0.5\n"
        "  council_daily_spend_ceiling_usd: 1.0\n"
        "  council_monthly_spend_ceiling_usd: 100.0\n"
    )
    cfg = _write_cfg(tmp_path, body)
    # $0.5/call, $1/day ceiling: one call is allowed, two reaches the ceiling.
    assert not ca.spend_ceiling_reached(1, 1, cfg)
    assert ca.spend_ceiling_reached(2, 2, cfg)
    # Monthly ceiling independently: 200 calls * $0.5 = $100 >= $100.
    assert ca.spend_ceiling_reached(0, 200, cfg)


def test_spend_ceiling_disabled_is_never_reached(tmp_path):
    cfg = _write_cfg(tmp_path, "strategy:\n  profile: swing\n")
    # Swing leaves the ceilings 0.0 (disabled), so no call count trips them.
    assert not ca.spend_ceiling_reached(10_000, 1_000_000, cfg)


def test_zero_est_cost_disables_the_ceiling(tmp_path):
    body = (
        "strategy:\n"
        "  profile: active_quant\n"
        "active_quant:\n"
        "  council_est_cost_per_call_usd: 0.0\n"
        "  council_daily_spend_ceiling_usd: 1.0\n"
    )
    cfg = _write_cfg(tmp_path, body)
    assert not ca.spend_ceiling_reached(100, 100, cfg)
