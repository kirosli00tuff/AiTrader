#pragma once
// Fee model (2026-07-26): cost per venue, asset class, and order type, from
// PUBLISHED LIVE SCHEDULES (config fees block), never from paper fills. The
// engine records this cost on every fill beside the venue figure. The
// backtest harness prices every trade with it. Order type is part of the
// cost: the engine sends market orders, which pay the taker rate.
#include <string>

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

// Cost a fill: sets the model figure and the order type on the row. The
// venue's reported figure stays in tr.fee, so the divergence is measurable.
// The engine's paper pnl accounting keeps the venue figure on purpose:
// repricing realized pnl would change tuner and gate behavior.
inline void apply_fee_model(const config::FeesConfig& f,
                            storage::TradeRow& tr) {
    const bool crypto = tr.category == "crypto";
    tr.fee_model_cost =
        per_side_fraction(f, crypto, OrderType::Taker) * tr.notional;
    tr.fee_order_type = "market_taker";
}

}  // namespace mal::fees
