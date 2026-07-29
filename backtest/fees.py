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


# Every key the fee model reads. Values live in the yaml ONLY: this module
# carried hard-coded fallback defaults until 2026-07-29, when the audit named
# them a latent fabrication (a regex miss or an omitted key would silently
# resurrect a stale figure). load() now refuses instead of defaulting.
FEE_KEYS = (
    "alpaca_crypto_maker_pct",
    "alpaca_crypto_taker_pct",
    "alpaca_crypto_tier_volume_threshold_usd",
    "alpaca_crypto_spread_bp_per_side",
    "alpaca_equity_commission_bp",
    "alpaca_equity_regulatory_bp_per_side",
    "alpaca_equity_spread_bp_per_side",
    "alpaca_equity_spread_tick_usd",
    "alpaca_equity_tier1_spread_tick_multiple",
    "alpaca_equity_tier2_spread_tick_multiple",
    "alpaca_equity_tier3_spread_tick_multiple",
    "alpaca_equity_tier4_spread_tick_multiple",
    "alpaca_equity_tier5_spread_tick_multiple",
    "alpaca_equity_tier6_spread_tick_multiple",
    "alpaca_equity_tier1_adv_floor_usd",
    "alpaca_equity_tier2_adv_floor_usd",
    "alpaca_equity_tier3_adv_floor_usd",
    "alpaca_equity_tier4_adv_floor_usd",
    "alpaca_equity_tier5_adv_floor_usd",
    "alpaca_equity_tier1_impact_bp_per_1k",
    "alpaca_equity_tier2_impact_bp_per_1k",
    "alpaca_equity_tier3_impact_bp_per_1k",
    "alpaca_equity_tier4_impact_bp_per_1k",
    "alpaca_equity_tier5_impact_bp_per_1k",
    "alpaca_equity_tier6_impact_bp_per_1k",
)


class FeeKeyUnreadable(RuntimeError):
    """A fee key is absent or written in a form the reader cannot parse.

    Raised instead of falling back to a hard-coded default (2026-07-29). A
    default here is a latent fabrication: a yaml omitting a key, or writing
    one in a form the regex does not match, would silently cost trades at a
    stale figure. Absence refuses.
    """


def load(config_path: str = DEFAULT_CONFIG) -> dict:
    """The fees block as a flat dict, read from the yaml.

    Refuses on any missing or unparseable key rather than defaulting: the
    shipped yaml carries every key (pinned by the mirror test), so a miss
    means either a broken yaml or a value form the reader cannot parse, and
    both must surface, never silently become a stale number.
    """
    text = open(config_path).read()
    out = {}
    unreadable = []
    for key in FEE_KEYS:
        # The whole value token is captured and float() decides whether it is
        # a number. The old pattern ([0-9.]+) took the longest numeric PREFIX,
        # so `1e-3` read as 1.0, a silent 1000x misread, and anything it could
        # not prefix-match fell to the stale default. Both paths now refuse,
        # and scientific notation parses correctly instead of wrongly.
        m = re.search(rf"^\s*{key}:\s*(\S+)", text, re.M)
        if m is None:
            unreadable.append(key)
            continue
        try:
            out[key] = float(m.group(1))
        except ValueError:
            unreadable.append(key)
    if unreadable:
        raise FeeKeyUnreadable(
            f"{config_path} is missing or has unparseable values for: "
            f"{', '.join(unreadable)}. Refusing to cost trades from "
            f"hard-coded defaults.")
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
