"""Fee model reader (2026-07-26): published live schedules, never paper fills.

Single source of truth is the fees block in config/default_config.yaml. This
module reads the same keys the C++ engine and harness read, and carries the
machine-readable Alpaca crypto tier table so a tier change is visible rather
than silent.

Sources, read 2026-07-26:
  * Alpaca published crypto fee schedule (volume-tiered maker/taker).
  * Alpaca published equity fee disclosure (commission free, regulatory
    fees on sells, spread borne by the order).
  * IBKR published pricing page. Which plan the live account uses could NOT
    be established this session and is recorded as such, never guessed.
"""
from __future__ import annotations

import os
import re

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEFAULT_CONFIG = os.path.join(REPO, "config", "default_config.yaml")

# Alpaca crypto tiers: (30-day volume floor USD, maker pct, taker pct).
# Source: Alpaca published crypto fee schedule, read 2026-07-26.
CRYPTO_TIERS = [
    (0, 0.15, 0.25),
    (100_000, 0.12, 0.22),
    (500_000, 0.10, 0.20),
    (1_000_000, 0.08, 0.18),
    (10_000_000, 0.05, 0.15),
    (25_000_000, 0.02, 0.10),
]


def crypto_tier(volume_30d_usd: float) -> tuple[float, float, float]:
    """(tier floor, maker pct, taker pct) for a 30-day volume."""
    row = CRYPTO_TIERS[0]
    for t in CRYPTO_TIERS:
        if volume_30d_usd >= t[0]:
            row = t
    return row


def load(config_path: str = DEFAULT_CONFIG) -> dict:
    """The fees block as a flat dict, read from the shipped yaml."""
    keys = {
        "alpaca_crypto_maker_pct": 0.15,
        "alpaca_crypto_taker_pct": 0.25,
        "alpaca_crypto_tier_volume_threshold_usd": 100000.0,
        "alpaca_crypto_spread_bp_per_side": 0.0,
        "alpaca_equity_commission_bp": 0.0,
        "alpaca_equity_regulatory_bp_per_side": 0.15,
        "alpaca_equity_spread_bp_per_side": 0.5,
        "alpaca_equity_spread_tick_usd": 0.01,
        "alpaca_equity_tier1_spread_tick_multiple": 1.0,
        "alpaca_equity_tier2_spread_tick_multiple": 1.0,
        "alpaca_equity_tier3_spread_tick_multiple": 8.0,
        "alpaca_equity_tier4_spread_tick_multiple": 9.0,
        "alpaca_equity_tier5_spread_tick_multiple": 1.0,
        "alpaca_equity_tier6_spread_tick_multiple": 1.0,
        "alpaca_equity_tier1_adv_floor_usd": 277000000.0,
        "alpaca_equity_tier2_adv_floor_usd": 65300000.0,
        "alpaca_equity_tier3_adv_floor_usd": 13300000.0,
        "alpaca_equity_tier4_adv_floor_usd": 2070000.0,
        "alpaca_equity_tier5_adv_floor_usd": 235000.0,
        "alpaca_equity_tier1_impact_bp_per_1k": 0.00024,
        "alpaca_equity_tier2_impact_bp_per_1k": 0.00114,
        "alpaca_equity_tier3_impact_bp_per_1k": 0.00543,
        "alpaca_equity_tier4_impact_bp_per_1k": 0.02847,
        "alpaca_equity_tier5_impact_bp_per_1k": 0.17320,
        "alpaca_equity_tier6_impact_bp_per_1k": 3.86400,
    }
    text = open(config_path).read()
    out = {}
    for key, default in keys.items():
        m = re.search(rf"^\s*{key}:\s*([0-9.]+)", text, re.M)
        out[key] = float(m.group(1)) if m else default
    return out


def per_side_bp(asset_class: str, order_type: str = "taker",
                fees: dict | None = None) -> float:
    """Per-side cost in bp of notional for one fill."""
    f = fees or load()
    if asset_class == "crypto":
        pct = (f["alpaca_crypto_taker_pct"] if order_type == "taker"
               else f["alpaca_crypto_maker_pct"])
        return pct * 100.0 + f["alpaca_crypto_spread_bp_per_side"]
    return (f["alpaca_equity_commission_bp"]
            + f["alpaca_equity_regulatory_bp_per_side"]
            + f["alpaca_equity_spread_bp_per_side"])


def round_trip_bp(asset_class: str, order_type: str = "taker",
                  fees: dict | None = None) -> float:
    return 2.0 * per_side_bp(asset_class, order_type, fees)


# --- Liquidity-aware equity cost (2026-07-27) ------------------------------- #
#
# Mirrors mal::fees in core/fees.hpp. THE FLAT 0.5 bp PER SIDE WAS NEVER
# MEASURED: it was recorded as an estimate on 2026-07-26, and measured on
# 2026-07-27 it is about right for the top 500 by liquidity and too low by 5x
# or more below that. Kept unchanged as the fallback for a symbol whose
# liquidity is unknown.
#
# SPREAD IS A FLOOR TIMES A MEASURED PER-TIER MULTIPLE, IMPACT IS MEASURED:
#   * One cent is the minimum quoted increment for a US equity above 1.00 USD
#     (SEC Reg NMS Rule 612), so tick/price is the tightest any market can be.
#     The multiple was MEASURED 2026-07-29 for tiers 3-4 from historical
#     consolidated SIP quotes (8.0 and 9.0 ticks median); tiers 1-2 and 5-6
#     stay at the 1.0 floor, unmeasured, stated in the yaml.
#   * Amihud (2002) illiquidity measured per tier over 11,710 US equities,
#     2025-07-01 to 2026-07-24, consolidated SIP. Scales with order size.

def equity_liquidity_tier(adv_usd: float, fees: dict | None = None) -> int:
    """1..6 by median daily dollar volume. 6 is the thinnest."""
    f = fees or load()
    for tier in range(1, 6):
        if adv_usd >= f[f"alpaca_equity_tier{tier}_adv_floor_usd"]:
            return tier
    return 6


def equity_spread_tick_multiple(adv_usd: float, fees: dict | None = None) -> float:
    """The tick multiple for a symbol's liquidity tier (2026-07-29).

    Tiers 3 and 4 are MEASURED from historical consolidated SIP quotes; tiers
    1, 2, 5 and 6 are 1.0 floors, unmeasured, stated in the yaml rather than
    guessed.
    """
    f = fees or load()
    tier = equity_liquidity_tier(adv_usd, f)
    return f[f"alpaca_equity_tier{tier}_spread_tick_multiple"]


def equity_per_side_bp(price: float, adv_usd: float, notional: float,
                       fees: dict | None = None) -> float:
    """Per-side equity cost in bp for one symbol at one order size.

    adv_usd <= 0 or price <= 0 means liquidity is UNKNOWN, and the flat legacy
    estimate is returned unchanged rather than a guessed tier.
    """
    f = fees or load()
    fixed = (f["alpaca_equity_commission_bp"]
             + f["alpaca_equity_regulatory_bp_per_side"])
    if price <= 0 or adv_usd <= 0:
        return fixed + f["alpaca_equity_spread_bp_per_side"]
    half_spread_bp = 0.5 * (f["alpaca_equity_spread_tick_usd"]
                            * equity_spread_tick_multiple(adv_usd, f)
                            / price) * 1e4
    tier = equity_liquidity_tier(adv_usd, f)
    impact_bp = (f[f"alpaca_equity_tier{tier}_impact_bp_per_1k"]
                 * notional / 1000.0)
    return fixed + half_spread_bp + impact_bp


def equity_round_trip_bp(price: float, adv_usd: float, notional: float,
                         fees: dict | None = None) -> float:
    return 2.0 * equity_per_side_bp(price, adv_usd, notional, fees)


def summary() -> dict:
    """The hurdle, for surfaces where decisions are made (GUI, reports)."""
    f = load()
    return {
        "order_type_assumed": "market_taker",
        "crypto_round_trip_bp": round(round_trip_bp("crypto", "taker", f), 3),
        "crypto_maker_round_trip_bp": round(
            round_trip_bp("crypto", "maker", f), 3),
        "equity_round_trip_bp": round(round_trip_bp("equity", "taker", f), 3),
        "crypto_tier_threshold_usd":
            f["alpaca_crypto_tier_volume_threshold_usd"],
        "source": "published live schedules, read 2026-07-26, "
                  "config/default_config.yaml fees block",
    }
