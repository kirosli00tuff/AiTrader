#include "execution/execution.hpp"

#include "core/util.hpp"

namespace mal::execution {

namespace {
Fill make_paper_fill(const risk::OrderProposal& o, const std::string& mode,
                     double fee_bps) {
    Fill f;
    f.venue = o.venue;
    f.symbol = o.symbol;
    f.side = o.side;
    f.mode = mode;
    f.qty = o.qty;
    f.price = o.price;
    f.notional = o.notional;
    f.fee = o.notional * fee_bps;
    f.ts = util::now_iso8601();
    f.executed = true;
    f.note = "paper fill";
    return f;
}
}  // namespace

Fill PolymarketPaperAdapter::place(const risk::OrderProposal& o) {
    // Polymarket paper trader bridge: simulate immediate fill at quoted price.
    return make_paper_fill(o, "paper", 0.0);  // Polymarket has no maker fee here
}

Fill AlpacaPaperAdapter::place(const risk::OrderProposal& o) {
    // Alpaca paper API: simulate fill (real impl would call the paper endpoint).
    return make_paper_fill(o, "paper", 0.0001);
}

Fill BinanceSimAdapter::place(const risk::OrderProposal& o) {
    // TODO: Binance — replace simulation with testnet/live adapter integration.
    return make_paper_fill(o, "paper", 0.0001);
}

Fill IbkrSimPlaceholderAdapter::place(const risk::OrderProposal& o) {
    // TODO: IBKR — this is a placeholder/sim only; complete real IBKR support.
    return make_paper_fill(o, "paper", 0.0002);
}

Fill DisabledLiveAdapter::place(const risk::OrderProposal& o) {
    // SAFETY: live adapters refuse to place orders. Live execution is disabled
    // by default and only the gated path may construct an enabled live adapter.
    Fill f;
    f.venue = o.venue;
    f.symbol = o.symbol;
    f.side = o.side;
    f.mode = "live";
    f.qty = o.qty;
    f.price = o.price;
    f.notional = o.notional;
    f.ts = util::now_iso8601();
    f.executed = false;
    f.note = "LIVE DISABLED: order refused by disabled live adapter";
    return f;
}

Fill ModeRouter::route(config::VenueMode mode, VenueAdapter& paper_adapter,
                       VenueAdapter& live_adapter, const risk::OrderProposal& o,
                       bool live_enabled) {
    switch (mode) {
        case config::VenueMode::Disabled: {
            Fill f;
            f.venue = o.venue;
            f.symbol = o.symbol;
            f.mode = "disabled";
            f.ts = util::now_iso8601();
            f.executed = false;
            f.note = "venue disabled";
            return f;
        }
        case config::VenueMode::RecommendationOnly: {
            Fill f;
            f.venue = o.venue;
            f.symbol = o.symbol;
            f.side = o.side;
            f.mode = "recommendation_only";
            f.qty = o.qty;
            f.price = o.price;
            f.notional = o.notional;
            f.ts = util::now_iso8601();
            f.executed = false;
            f.note = "recommendation only — no order placed";
            return f;
        }
        case config::VenueMode::Paper:
            return paper_adapter.place(o);
        case config::VenueMode::Live: {
            // SAFETY: even in live mode, refuse unless live is explicitly
            // enabled for this venue (approval gate already passed upstream).
            if (!live_enabled) {
                Fill f;
                f.venue = o.venue;
                f.symbol = o.symbol;
                f.mode = "live";
                f.ts = util::now_iso8601();
                f.executed = false;
                f.note = "live not enabled — refused";
                return f;
            }
            return live_adapter.place(o);
        }
    }
    Fill f;
    f.executed = false;
    f.note = "unknown mode";
    return f;
}

}  // namespace mal::execution
