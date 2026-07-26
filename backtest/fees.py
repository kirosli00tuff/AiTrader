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
