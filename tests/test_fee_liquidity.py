"""Liquidity-aware equity cost (2026-07-27).

WHY THIS EXISTS. The fee model carried ONE equity figure, 1.3 bp round trip,
built against a top-500-by-liquidity universe. Measured on 2026-07-27 across
11,710 US equities, that figure is right for the top 500 and wrong by 5x or
more below it, reaching 33x in the thinnest band. A planned experiment trades
small caps deliberately, because the news-drift effect concentrates there, so
the wrong hurdle would have made every measurement in that band meaningless.
Same shape as the crypto error, where paper fills understated live cost 25x.

WHAT IS PINNED, AND AT WHICH STRENGTH:
  * spread is a FLOOR from the Reg NMS one-cent increment, so it scales as
    1/price and can never be beaten,
  * impact is MEASURED Amihud illiquidity by tier and scales with order size,
  * unknown liquidity falls back to the flat legacy figure UNCHANGED, so no
    caller without bar history is silently recosted,
  * crypto is untouched, because its schedule has no liquidity axis,
  * and the C++ and Python halves agree, because two copies of a cost model
    are how two halves of a system come to disagree about what a trade costs.
"""
from __future__ import annotations

import os
import re

import pytest

from backtest import fees

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
YAML = os.path.join(REPO, "config", "default_config.yaml")
CFG_HPP = os.path.join(REPO, "config", "config.hpp")
FEES_HPP = os.path.join(REPO, "core", "fees.hpp")
BT = os.path.join(REPO, "core", "backtest_main.cpp")

ORDER = 5000.0


# ---- the tier ladder ------------------------------------------------------

def test_tiers_run_from_most_to_least_liquid():
    f = fees.load()
    assert fees.equity_liquidity_tier(1e9, f) == 1
    assert fees.equity_liquidity_tier(300e6, f) == 1
    assert fees.equity_liquidity_tier(100e6, f) == 2
    assert fees.equity_liquidity_tier(20e6, f) == 3
    assert fees.equity_liquidity_tier(5e6, f) == 4
    assert fees.equity_liquidity_tier(500e3, f) == 5
    assert fees.equity_liquidity_tier(1e3, f) == 6
    assert fees.equity_liquidity_tier(0.0, f) == 6


def test_impact_rises_monotonically_as_liquidity_falls():
    f = fees.load()
    prev = -1.0
    for adv in (1e9, 100e6, 20e6, 5e6, 500e3, 1e3):
        tier = fees.equity_liquidity_tier(adv, f)
        imp = f[f"alpaca_equity_tier{tier}_impact_bp_per_1k"]
        assert imp > prev, "a thinner name must never cost less to move"
        prev = imp


# ---- a small cap costs more than a mega cap -------------------------------

def test_a_small_cap_costs_more_than_a_mega_cap():
    """THE WHOLE POINT. Same order size, three very different names."""
    mega = fees.equity_round_trip_bp(600.0, 500e6, ORDER)   # SPY-shaped
    small = fees.equity_round_trip_bp(12.0, 400e3, ORDER)   # thin small cap
    micro = fees.equity_round_trip_bp(4.0, 40e3, ORDER)     # near-untradeable
    assert mega < small < micro
    assert small > 4 * mega
    assert micro > 20 * mega


def test_the_top_band_lands_near_the_figure_the_old_model_assumed():
    """The old 1.3 bp was not wrong for the universe it was built on, and that
    is why nobody caught it. A mega cap still costs about that."""
    assert fees.equity_round_trip_bp(600.0, 500e6, ORDER) == pytest.approx(
        0.6, abs=0.3)


# ---- spread is a floor, and behaves like one ------------------------------

def test_spread_scales_as_one_over_price_because_the_tick_is_fixed():
    """A penny on a 500 dollar share is 0.2 bp; on a 5 dollar share it is
    20 bp. Same tick, 100x the proportional cost."""
    f = fees.load()
    hi = fees.equity_per_side_bp(500.0, 1e9, ORDER, f)
    lo = fees.equity_per_side_bp(5.0, 1e9, ORDER, f)
    fixed = f["alpaca_equity_regulatory_bp_per_side"]
    assert (lo - fixed) == pytest.approx(100.0 * (hi - fixed), rel=0.02)


def test_the_tick_multiple_ships_at_one_which_is_the_floor():
    """The model UNDERSTATES small-cap spread by construction and must say so.
    No quote data exists in this project to measure how many ticks wide a
    market really is, so the multiple is 1.0 until it can be measured."""
    f = fees.load()
    assert f["alpaca_equity_spread_tick_multiple"] == 1.0
    assert f["alpaca_equity_spread_tick_usd"] == 0.01


def test_raising_the_tick_multiple_raises_only_the_spread_component():
    f = fees.load()
    base = fees.equity_per_side_bp(10.0, 1e9, ORDER, f)
    f2 = dict(f, alpaca_equity_spread_tick_multiple=3.0)
    wide = fees.equity_per_side_bp(10.0, 1e9, ORDER, f2)
    fixed = f["alpaca_equity_regulatory_bp_per_side"]
    assert (wide - fixed) == pytest.approx(3.0 * (base - fixed), rel=0.01)


# ---- impact scales with order size ----------------------------------------

def test_impact_scales_with_order_size_and_spread_does_not():
    """5,000 USD is nothing in a mega cap and can exceed a day's volume in the
    thinnest band, so cost has to depend on size."""
    f = fees.load()
    small_order = fees.equity_per_side_bp(10.0, 50e3, 1000.0, f)
    big_order = fees.equity_per_side_bp(10.0, 50e3, 10000.0, f)
    assert big_order > small_order
    # In a mega cap the size term is negligible, which is why the flat figure
    # survived as long as it did.
    a = fees.equity_per_side_bp(600.0, 1e9, 1000.0, f)
    b = fees.equity_per_side_bp(600.0, 1e9, 10000.0, f)
    assert b - a < 0.01


# ---- unknown liquidity falls back, it does not guess ----------------------

def test_unknown_liquidity_uses_the_flat_legacy_figure_unchanged():
    """A caller with no bar history is costed exactly as before 2026-07-27.
    Guessing a tier for a symbol whose liquidity was never measured is the
    fabrication this project keeps correcting."""
    assert fees.equity_per_side_bp(100.0, 0.0, ORDER) == pytest.approx(0.65)
    assert fees.equity_per_side_bp(0.0, 1e9, ORDER) == pytest.approx(0.65)
    assert fees.equity_round_trip_bp(100.0, 0.0, ORDER) == pytest.approx(1.3)


def test_the_flat_equity_figure_did_not_move():
    """It was 0.5 bp per side before this session and it is 0.5 after. The
    change ADDS a liquidity path, it does not recalibrate the old one."""
    assert fees.load()["alpaca_equity_spread_bp_per_side"] == 0.5
    assert fees.per_side_bp("equity", "taker") == pytest.approx(0.65)
    assert fees.round_trip_bp("equity", "taker") == pytest.approx(1.3)


def test_crypto_is_untouched():
    assert fees.round_trip_bp("crypto", "taker") == 50.0
    assert fees.round_trip_bp("crypto", "maker") == 30.0


# ---- the two halves agree -------------------------------------------------

def test_every_new_key_exists_in_yaml_hpp_and_python():
    """Two copies of a cost model is how two halves of a system come to
    disagree about what a trade costs."""
    yaml, hpp = open(YAML).read(), open(CFG_HPP).read()
    keys = [k for k in fees.load() if "tier" in k or "spread_tick" in k]
    keys = [k for k in keys if "crypto" not in k]
    assert len(keys) == 13, f"expected the 13 new keys, found {len(keys)}"
    for k in keys:
        assert re.search(rf"^\s*{k}:", yaml, re.M), f"{k} missing from yaml"
        assert re.search(rf"\b{k}\b", hpp), f"{k} missing from FeesConfig"


def test_the_python_and_cpp_tier_ladders_have_the_same_shape():
    cpp = open(FEES_HPP).read()
    for tier in range(1, 6):
        assert f"alpaca_equity_tier{tier}_adv_floor_usd" in cpp
    for tier in range(1, 7):
        assert f"alpaca_equity_tier{tier}_impact_bp_per_1k" in cpp
    assert "equity_per_side_fraction" in cpp
    assert "median_dollar_volume" in cpp


def test_the_harness_prices_equity_per_symbol_not_once():
    """MUTATION GUARD. Restoring a single resolved-once equity fee fraction
    reinstates exactly the defect this session fixed: every name, mega cap to
    micro cap, charged the same 1.3 bp."""
    src = "\n".join(re.sub(r"//.*$", "", ln)
                    for ln in open(BT).read().splitlines())
    assert "fees::equity_per_side_fraction" in src, (
        "the harness no longer prices equity per symbol")
    assert not re.search(r"const double fee_side_equity\s*=", src), (
        "a resolved-once equity fee fraction is back; every symbol would be "
        "charged the top-500 rate again")
    assert "entry_side_fee" in src, (
        "the exit must reuse the entry's per-side fraction, or a round trip "
        "mixes two different symbols' costs")
