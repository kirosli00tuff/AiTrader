"""The three latent fallbacks AUDIT-2026-07-29.md named, closed (2026-07-29).

Every one of the seven recorded fabrications was found by someone looking
before it fired. These three had the fabrication shape and no trigger yet:

  1. The experiment scoring path inherited the engine's flat-cost fallback
     when ADV is absent, which in the band understates measured cost 14x to
     40x. The ENGINE keeps its deliberate, pinned fallback. The EXPERIMENT
     path now refuses the row (`adv_unavailable`).
  2. A model response without a usage block read as zero tokens, so a call
     whose cost was unknown recorded as FREE and the spend ceiling had a
     hole. Unknown is not free: the row refuses and the ceiling is charged
     the projected per-call cost.
  3. `fees.load()` fell back to a hard-coded default on a regex miss, so an
     omitted or oddly written key silently resurrected a stale figure, and
     the prefix-matching pattern read `1e-3` as 1.0. It now refuses, and
     scientific notation parses correctly.

EVERY CLOSED PATH IS PRODUCED, NOT ASSERTED, through the real code down its
real branch. Each test states the mutation that must make it fail.
"""
from __future__ import annotations

import os

import pytest

from backtest import fees
from news_experiment import spec
from news_experiment.horizon import Calendar
from news_experiment.outcomes import PriceBook, resolve_one
from news_experiment.scoring import (ERROR_USAGE_MISSING, Scorer,
                                     SpendCeiling)

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SHIPPED_YAML = os.path.join(REPO, "config", "default_config.yaml")


# ---- 1. an absent ADV refuses in the experiment path ----------------------

SESSIONS = ("2026-01-05", "2026-01-06", "2026-01-07")


def _cal() -> Calendar:
    return Calendar.from_rows([(s, "09:30", "16:00") for s in SESSIONS])


def _book() -> PriceBook:
    book = PriceBook()
    for s in SESSIONS:
        book.opens[("AAA", s)] = 40.0
        book.closes[("AAA", s)] = 40.4
        book.source[("AAA", s)] = "backfill"
    return book


def _resolve(adv):
    return resolve_one(symbol="AAA", judgment=spec.JUDGMENT_POSITIVE,
                       anchor_kind=spec.ANCHOR_NEXT_SESSION_OPEN,
                       anchor_session=SESSIONS[0],
                       scoring_session=SESSIONS[1], adv_usd=adv,
                       notional=2000.0, book=_book(), cal=_cal(),
                       band_members=["AAA"])


def test_an_absent_adv_refuses_rather_than_costing_flat():
    """MUTATION: remove the adv_usd precondition in resolve_one. The row then
    resolves with cost_bp_round_trip 1.3, the flat legacy figure, optimistic
    14x to 40x in this band, and both asserts fail."""
    for adv in (None, 0.0, -1.0):
        out = _resolve(adv)
        assert out.outcome_state == "excluded", adv
        assert out.exclusion_reason == spec.EXCLUSION_ADV_UNAVAILABLE
        assert out.cost_bp_round_trip is None
        assert out.net_bp is None


def test_a_present_adv_still_resolves_with_the_tiered_cost():
    """The refusal is a precondition, not a recosting: a band ADV resolves
    exactly as before, at its own tier's measured cost, well above flat."""
    out = _resolve(3_000_000.0)   # S4 tier
    assert out.outcome_state == "resolved"
    assert out.cost_bp_round_trip is not None
    assert out.cost_bp_round_trip > 1.3


def test_the_engine_flat_fallback_itself_is_untouched():
    """The ENGINE's deliberate unknown-liquidity fallback stays pinned: the
    closure is scoped to the experiment path, not a recalibration."""
    assert fees.equity_round_trip_bp(100.0, 0.0, 5000.0) == pytest.approx(1.3)


def test_adv_unavailable_is_a_registered_exclusion_reason():
    assert spec.EXCLUSION_ADV_UNAVAILABLE in spec.EXCLUSION_REASONS


# ---- 2. unknown provider usage is not zero spend --------------------------

VERDICT_TEXT = '{"judgment": "POSITIVE", "strength": 3, "reason": "beat"}'


def _poster_returning(resp):
    def poster(url, headers, payload):
        return resp
    return poster


def _scored(resp):
    ceiling = SpendCeiling(limit_usd=1.0)
    scorer = Scorer(key="k", label="anthropic_experiment_test",
                    ceiling=ceiling, poster=_poster_returning(resp))
    return scorer.score("AAA", "AAA beats"), ceiling, scorer


def test_a_response_without_usage_refuses_and_charges_projected():
    """MUTATION: restore `usage = resp.get('usage') or {}` with or-0 token
    reads. The call then lands `judged` at cost 0.0, the ceiling stays at
    0.0 spent, and every assert here fails."""
    result, ceiling, scorer = _scored(
        {"content": [{"type": "text", "text": VERDICT_TEXT}]})
    assert result.state == spec.STATE_MODEL_FAILED
    assert result.error_class == ERROR_USAGE_MISSING
    assert result.judgment is None
    assert result.cost_usd == pytest.approx(spec.PROJECTED_COST_PER_CALL)
    assert ceiling.spent_usd == pytest.approx(spec.PROJECTED_COST_PER_CALL)
    assert scorer.failures == 1


def test_partial_usage_missing_output_tokens_also_refuses():
    """MUTATION: same as above, or read output_tokens with `or 0`. Half a
    usage block is still an unknown cost."""
    result, ceiling, _ = _scored(
        {"content": [{"type": "text", "text": VERDICT_TEXT}],
         "usage": {"input_tokens": 340}})
    assert result.state == spec.STATE_MODEL_FAILED
    assert result.error_class == ERROR_USAGE_MISSING
    assert ceiling.spent_usd == pytest.approx(spec.PROJECTED_COST_PER_CALL)


def test_absent_cache_fields_are_no_caching_not_unknown_spend():
    """An absent cache field means no caching happened, a documented
    semantic. The row scores normally at the metered cost."""
    result, ceiling, _ = _scored(
        {"content": [{"type": "text", "text": VERDICT_TEXT}],
         "usage": {"input_tokens": 340, "output_tokens": 40}})
    assert result.state == spec.STATE_JUDGED
    assert result.judgment == spec.JUDGMENT_POSITIVE
    assert result.cost_usd > 0.0
    assert ceiling.spent_usd == pytest.approx(result.cost_usd)


def test_usage_missing_is_a_registered_model_failed_class():
    assert ERROR_USAGE_MISSING in spec.ERROR_CLASSES_MODEL_FAILED


# ---- 3. a fee key the reader cannot read refuses --------------------------

def _yaml_without(tmp_path, key):
    lines = [ln for ln in open(SHIPPED_YAML).read().splitlines()
             if not ln.strip().startswith(f"{key}:")]
    path = tmp_path / "config.yaml"
    path.write_text("\n".join(lines))
    return str(path)


def test_a_yaml_omitting_a_key_refuses_rather_than_defaulting(tmp_path):
    """MUTATION: restore `out[key] = float(m.group(1)) if m else default` in
    fees.load. The omitted key then silently reads its stale hard-coded
    value and the raise never happens."""
    path = _yaml_without(tmp_path, "alpaca_equity_tier3_spread_tick_multiple")
    with pytest.raises(fees.FeeKeyUnreadable) as err:
        fees.load(path)
    assert "alpaca_equity_tier3_spread_tick_multiple" in str(err.value)


def test_a_value_the_reader_cannot_parse_refuses(tmp_path):
    lines = open(SHIPPED_YAML).read().replace(
        "alpaca_equity_tier4_spread_tick_multiple: 9.0",
        "alpaca_equity_tier4_spread_tick_multiple: measured")
    path = tmp_path / "config.yaml"
    path.write_text(lines)
    with pytest.raises(fees.FeeKeyUnreadable) as err:
        fees.load(str(path))
    assert "alpaca_equity_tier4_spread_tick_multiple" in str(err.value)


def test_scientific_notation_parses_correctly_instead_of_as_its_prefix(
        tmp_path):
    """The old pattern took the longest numeric PREFIX, so 1e-3 read as 1.0,
    a silent 1000x misread worse than the default it replaced. MUTATION:
    restore ([0-9.]+) and this reads 1.0."""
    lines = open(SHIPPED_YAML).read().replace(
        "alpaca_equity_tier2_impact_bp_per_1k: 0.00114",
        "alpaca_equity_tier2_impact_bp_per_1k: 1e-3")
    path = tmp_path / "config.yaml"
    path.write_text(lines)
    f = fees.load(str(path))
    assert f["alpaca_equity_tier2_impact_bp_per_1k"] == pytest.approx(0.001)


def test_the_shipped_yaml_still_loads_every_key(tmp_path):
    f = fees.load()
    assert len(f) == len(fees.FEE_KEYS)
    assert f["alpaca_equity_tier3_spread_tick_multiple"] == 8.0
    assert f["alpaca_equity_tier4_spread_tick_multiple"] == 9.0
