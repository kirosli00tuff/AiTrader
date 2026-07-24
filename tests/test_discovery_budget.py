"""The discovery budget charges provider CONTACT, never evaluator returns.

The 2026-07-17 burn is the spec: 10 of 12 daily calls were spent by
evaluations whose council short-circuited (gate decline, risk pre-check,
market-hours skip) and contacted no provider, because the counter incremented
on every evaluator RETURN. store.record_pass persisted the count, so the burn
outlived the process. These tests pin the corrected accounting end to end:
funnel counter, verdict reporting, pass persistence.

No network: gates and evaluators are mocks, and the one consensus() call runs
the deterministic offline mock providers with an always-proceed gate.
"""
from __future__ import annotations

import sqlite3

from discovery import evaluate, funnel


def _short_circuit_verdict(symbol: str) -> dict:
    """What Stage C produces when consensus() short-circuits: a flat avoid
    with zero providers scored."""
    return {"symbol": symbol, "verdict": "avoid", "conviction": 0.0,
            "provider_calls": 0}


def _real_verdict(symbol: str) -> dict:
    """What Stage C produces when the council actually ran three providers."""
    return {"symbol": symbol, "verdict": "avoid", "conviction": 0.55,
            "provider_calls": 3}


# --- The counter itself ------------------------------------------------------

def test_short_circuited_evaluation_costs_zero_budget():
    candidates, drops, calls = funnel.evaluate_survivors(
        ["AA/USD", "BB/USD"], _short_circuit_verdict,
        max_council_calls=5, budget_remaining=5)
    assert calls == 0
    assert len(candidates) == 2          # still evaluated and still recorded
    assert drops == []


def test_provider_contacting_evaluation_costs_one_each():
    candidates, drops, calls = funnel.evaluate_survivors(
        ["AA/USD", "BB/USD", "CC/USD"], _real_verdict,
        max_council_calls=5, budget_remaining=5)
    assert calls == 3
    assert len(candidates) == 3


# --- Calibrated estimates + the equity reservation (2026-07-23) --------------

def test_shipped_discovery_and_research_estimates_are_the_measured_value():
    """Both estimates price the SAME council the trading tier runs, so both
    carry the measured $0.056/round. Reads the real shipped file AND the
    fallback defaults, so a drift in either direction fails here: 0.04
    understated discovery spend by 40 percent, and 0.08 overstated research
    spend by 43 percent against the combined ceiling."""
    from discovery import settings
    from llm_consensus import config_access as ca
    shipped = "config/default_config.yaml"
    assert settings.discovery_est_cost_per_call_usd(shipped) == 0.056
    assert settings._DEFAULTS["discovery_est_cost_per_call_usd"] == 0.056
    assert ca.research_est_cost_per_call_usd(shipped) == 0.056
    assert ca._SLEEVE_DEFAULTS["research_est_cost_per_call_usd"] == 0.056


def test_equity_reservation_caps_crypto_while_a_session_is_ahead():
    """The reserved equity Stage-C budget (Task 3, 2026-07-23): crypto may
    not spend into the reservation while a US session is still ahead or open
    that UTC day, equities always see the full budget (their cadence already
    restricts them to US hours), and after the close or on a weekend the
    unused reservation is RELEASED to crypto rather than silently expiring."""
    from datetime import datetime, timezone
    from discovery.run import effective_daily_budget
    shipped = "config/default_config.yaml"
    wd_pre = datetime(2026, 7, 22, 6, 0, tzinfo=timezone.utc)
    wd_open = datetime(2026, 7, 22, 15, 0, tzinfo=timezone.utc)
    wd_post = datetime(2026, 7, 22, 21, 0, tzinfo=timezone.utc)
    weekend = datetime(2026, 7, 25, 6, 0, tzinfo=timezone.utc)
    assert effective_daily_budget("crypto", wd_pre, shipped) == 8
    assert effective_daily_budget("crypto", wd_open, shipped) == 8
    assert effective_daily_budget("crypto", wd_post, shipped) == 12
    assert effective_daily_budget("crypto", weekend, shipped) == 12
    assert effective_daily_budget("equity", wd_pre, shipped) == 12
    assert effective_daily_budget("equity", wd_open, shipped) == 12


def test_reservation_is_clamped_to_the_total():
    """A misconfigured reservation can never exceed the pool it reserves
    from: the getter clamps to [0, daily budget]."""
    from discovery import settings
    assert 0 <= settings.discovery_equity_reserved_calls() <= \
        settings.discovery_daily_council_budget()


def test_run_pass_honors_the_daily_budget_override():
    """run_pass takes the per-class allocation as an explicit budget, so the
    reservation binds Stage C exactly like the configured total does."""
    result = funnel.run_pass(
        "crypto",
        snapshots=[{"symbol": f"S{i}/USD", "price": 100.0,
                    "change_pct": 5.0 - i * 0.1, "high": 106.0, "low": 99.0,
                    "open": 100.0, "prev_close": 100.0} for i in range(4)],
        gate=type("G", (), {"should_review": staticmethod(
            lambda state: type("D", (), {"proceed": True, "reason": "ok"})())})(),
        evaluator=lambda s: {"symbol": s, "verdict": "avoid",
                             "conviction": 0.0, "provider_calls": 3},
        calls_used_today=8, daily_budget=8)
    # 8 of the crypto cap of 8 already used: no gate call, no council call.
    assert result.status == "budget_exhausted"
    assert result.council_calls == 0
    assert result.gate_calls == 0


def test_evaluator_that_does_not_report_is_charged_conservatively():
    # An unknown evaluator must never spend unbounded: no provider_calls field
    # reads as one full call, the pre-fix accounting.
    candidates, drops, calls = funnel.evaluate_survivors(
        ["AA/USD"], lambda s: {"symbol": s, "verdict": "avoid"},
        max_council_calls=5, budget_remaining=5)
    assert calls == 1


def test_short_circuits_do_not_eat_the_ceiling():
    # Three short-circuits then two real calls against a ceiling of 1: the
    # short-circuits are free, the first real call spends the ceiling, the
    # second real call is dropped with the true reason.
    def ev(symbol):
        return (_real_verdict(symbol) if symbol.startswith("REAL")
                else _short_circuit_verdict(symbol))

    candidates, drops, calls = funnel.evaluate_survivors(
        ["A/USD", "B/USD", "C/USD", "REAL1/USD", "REAL2/USD"], ev,
        max_council_calls=1, budget_remaining=5)
    assert calls == 1
    assert [c["symbol"] for c in candidates] == [
        "A/USD", "B/USD", "C/USD", "REAL1/USD"]
    assert [d.symbol for d in drops] == ["REAL2/USD"]
    assert drops[0].reason == "pass_council_ceiling"


def test_budget_cost_rules():
    assert funnel._budget_cost({"provider_calls": 0}) == 0
    assert funnel._budget_cost({"provider_calls": 3}) == 1
    assert funnel._budget_cost({"provider_calls": 1}) == 1
    assert funnel._budget_cost({}) == 1                  # unreported: charged
    assert funnel._budget_cost({"provider_calls": "x"}) == 1
    assert funnel._budget_cost(None) == 1
    assert funnel._budget_cost("not a dict") == 1


# --- The verdict reports contact honestly ------------------------------------

def test_build_verdict_reports_zero_provider_calls_on_a_short_circuit():
    from llm_consensus.consensus import _flat_consensus
    from llm_consensus.gate import GateDecision
    flat = _flat_consensus(GateDecision(
        False, "risk pre-check: blocked", "risk_precheck", "risk_precheck"))
    v = evaluate.build_verdict(symbol="AA/USD", council=flat, dnn={}, whale={})
    assert v["provider_calls"] == 0
    assert v["verdict"] == "avoid"


def test_build_verdict_reports_scored_providers_on_a_real_run():
    from llm_consensus.consensus import consensus, default_providers
    from llm_consensus.gate import AlwaysProceedGate
    council = consensus(
        {"symbol": "BTC-USD", "ret_5": 0.02, "imbalance": 0.3,
         "catalyst": 0.4},
        providers=default_providers(), gate=AlwaysProceedGate())
    v = evaluate.build_verdict(symbol="BTC-USD", council=council,
                               dnn={}, whale={})
    assert v["provider_calls"] == 3      # three mock slots, all scored


# --- End to end through run_pass and the persisted count ----------------------

class _ProceedGate:
    def should_review(self, state):
        class D:
            proceed = True
            reason = "ok"
        return D()


def _snapshot(symbol: str) -> dict:
    return {"symbol": symbol, "price": 100.0, "change_pct": 6.0,
            "high": 106.0, "low": 98.0, "open": 100.0, "prev_close": 99.0}


def test_run_pass_records_zero_council_calls_when_all_short_circuit():
    result = funnel.run_pass(
        "crypto",
        snapshots=[_snapshot("AA/USD"), _snapshot("BB/USD")],
        gate=_ProceedGate(),
        evaluator=_short_circuit_verdict,
        calls_used_today=10)
    assert result.council_calls == 0
    assert result.est_cost_usd == 0.0
    assert len(result.candidates) == 2

    # And the persisted count carries the same zero, so the burn cannot
    # outlive the process the way the 07-17 one did.
    conn = sqlite3.connect(":memory:")
    from discovery import store
    pass_id = store.record_pass(conn, result.to_dict())
    row = conn.execute(
        "SELECT council_calls FROM discovery_pass WHERE id=?",
        (pass_id,)).fetchone()
    assert row[0] == 0
    conn.close()


def test_run_pass_still_charges_real_calls():
    result = funnel.run_pass(
        "crypto",
        snapshots=[_snapshot("AA/USD"), _snapshot("BB/USD")],
        gate=_ProceedGate(),
        evaluator=_real_verdict,
        calls_used_today=0)
    assert result.council_calls == 2
    assert result.est_cost_usd > 0.0
