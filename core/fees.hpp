#pragma once
// Fee model (2026-07-26): cost per venue, asset class, and order type, from
// PUBLISHED LIVE SCHEDULES (config fees block), never from paper fills. The
// engine records this cost on every fill beside the venue figure. The
// backtest harness prices every trade with it. Order type is part of the
// cost: the engine sends market orders, which pay the taker rate.
#include <algorithm>
#include <string>
#include <vector>

#include "config/config.hpp"
#include "storage/storage.hpp"

namespace mal::fees {

enum class OrderType { Maker, Taker };

// Per-side cost as a FRACTION of notional.
inline double per_side_fraction(const config::FeesConfig& f, bool is_crypto,
                                OrderType ot) {
    if (is_crypto) {
        const double pct = ot == OrderType::Taker ? f.alpaca_crypto_taker_pct
                                                  : f.alpaca_crypto_maker_pct;
        return pct / 100.0 + f.alpaca_crypto_spread_bp_per_side / 1e4;
    }
    return (f.alpaca_equity_commission_bp +
            f.alpaca_equity_regulatory_bp_per_side +
            f.alpaca_equity_spread_bp_per_side) / 1e4;
}

inline double round_trip_fraction(const config::FeesConfig& f, bool is_crypto,
                                  OrderType ot) {
    return 2.0 * per_side_fraction(f, is_crypto, ot);
}

// --- Liquidity-aware equity cost (2026-07-27) --------------------------------
//
// THE FLAT 0.5 bp PER SIDE WAS NEVER MEASURED. It was recorded as an estimate
// on 2026-07-26 and measured on 2026-07-27: about right for the top 500 by
// liquidity and too low by 5x or more below that. A single figure calibrated
// on large caps does not apply to small ones, which matters because the
// news-drift effect a planned experiment targets concentrates in exactly the
// names the flat figure gets wrong.
//
// Two components, and they are NOT the same kind of number:
//   SPREAD is a FLOOR. One cent is the minimum quoted increment for a US
//   equity above 1.00 USD (Reg NMS Rule 612), so tick/price is the tightest
//   any market can be and half of it is the tightest per-side cost. Real small
//   caps quote several ticks wide. No quote data exists here to measure how
//   many, so the multiple ships at 1.0 and this UNDERSTATES by construction.
//   IMPACT is MEASURED. Amihud (2002) illiquidity by liquidity tier, from
//   11,710 US equities over 2025-07-01 to 2026-07-24. It scales with order
//   size, which is the point: 5,000 USD is nothing in a mega cap and can
//   exceed a full day's volume in the thinnest band.
//
// A LABEL, NOT A GATE. Nothing here refuses an order or sizes one.

// bp per side per 1,000 USD of notional for a symbol's liquidity tier.
inline double equity_impact_bp_per_1k(const config::FeesConfig& f,
                                      double adv_usd) {
    if (adv_usd >= f.alpaca_equity_tier1_adv_floor_usd)
        return f.alpaca_equity_tier1_impact_bp_per_1k;
    if (adv_usd >= f.alpaca_equity_tier2_adv_floor_usd)
        return f.alpaca_equity_tier2_impact_bp_per_1k;
    if (adv_usd >= f.alpaca_equity_tier3_adv_floor_usd)
        return f.alpaca_equity_tier3_impact_bp_per_1k;
    if (adv_usd >= f.alpaca_equity_tier4_adv_floor_usd)
        return f.alpaca_equity_tier4_impact_bp_per_1k;
    if (adv_usd >= f.alpaca_equity_tier5_adv_floor_usd)
        return f.alpaca_equity_tier5_impact_bp_per_1k;
    return f.alpaca_equity_tier6_impact_bp_per_1k;
}

// 1..6, for reporting which tier a fill was costed in.
inline int equity_liquidity_tier(const config::FeesConfig& f, double adv_usd) {
    if (adv_usd >= f.alpaca_equity_tier1_adv_floor_usd) return 1;
    if (adv_usd >= f.alpaca_equity_tier2_adv_floor_usd) return 2;
    if (adv_usd >= f.alpaca_equity_tier3_adv_floor_usd) return 3;
    if (adv_usd >= f.alpaca_equity_tier4_adv_floor_usd) return 4;
    if (adv_usd >= f.alpaca_equity_tier5_adv_floor_usd) return 5;
    return 6;
}

// Per-side EQUITY cost as a fraction of notional, aware of the symbol's price
// and its liquidity. adv_usd <= 0 or price <= 0 means liquidity is UNKNOWN and
// the flat legacy estimate is used unchanged, so a caller with no bar history
// is costed exactly as before rather than by a guessed tier.
inline double equity_per_side_fraction(const config::FeesConfig& f,
                                       double price, double adv_usd,
                                       double notional) {
    const double fixed =
        (f.alpaca_equity_commission_bp +
         f.alpaca_equity_regulatory_bp_per_side) / 1e4;
    if (price <= 0.0 || adv_usd <= 0.0)
        return fixed + f.alpaca_equity_spread_bp_per_side / 1e4;
    const double half_spread = 0.5 * f.alpaca_equity_spread_tick_usd *
                               f.alpaca_equity_spread_tick_multiple / price;
    const double impact =
        equity_impact_bp_per_1k(f, adv_usd) * (notional / 1000.0) / 1e4;
    return fixed + half_spread + impact;
}

// Round trip for one equity name at one order size.
inline double equity_round_trip_fraction(const config::FeesConfig& f,
                                         double price, double adv_usd,
                                         double notional) {
    return 2.0 * equity_per_side_fraction(f, price, adv_usd, notional);
}

// Median daily dollar volume from a rolling bar history. The liquidity input
// both the engine and the harness already have, computed one way so the two
// cannot disagree about what a tier means. Returns 0 when there is no history,
// which the cost functions read as "unknown" rather than "illiquid".
inline double median_dollar_volume(const std::vector<double>& closes,
                                   const std::vector<double>& volumes) {
    std::vector<double> dv;
    const size_t n = std::min(closes.size(), volumes.size());
    dv.reserve(n);
    for (size_t i = 0; i < n; ++i)
        if (closes[i] > 0.0 && volumes[i] > 0.0)
            dv.push_back(closes[i] * volumes[i]);
    if (dv.empty()) return 0.0;
    std::sort(dv.begin(), dv.end());
    const size_t m = dv.size() / 2;
    return dv.size() % 2 ? dv[m] : 0.5 * (dv[m - 1] + dv[m]);
}

// Cost a fill: sets the model figure and the order type on the row. The
// venue's reported figure stays in tr.fee, so the divergence is measurable.
// The engine's paper pnl accounting keeps the venue figure on purpose:
// repricing realized pnl would change tuner and gate behavior.
// adv_usd is the symbol's median daily dollar volume, 0 when unknown. On an
// EQUITY fill a known value selects the liquidity-aware cost above; unknown
// falls back to the flat estimate, so an engine with no bar history for the
// name is costed exactly as it was before 2026-07-27. Crypto is unaffected:
// its schedule is a published percentage and carries no liquidity axis.
inline void apply_fee_model(const config::FeesConfig& f,
                            storage::TradeRow& tr, double adv_usd = 0.0) {
    const bool crypto = tr.category == "crypto";
    const double side =
        crypto ? per_side_fraction(f, true, OrderType::Taker)
               : equity_per_side_fraction(f, tr.price, adv_usd, tr.notional);
    tr.fee_model_cost = side * tr.notional;
    tr.fee_order_type = "market_taker";
}

}  // namespace mal::fees
