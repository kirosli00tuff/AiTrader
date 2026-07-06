#include "execution/execution.hpp"

#include <sstream>

#include "core/bridge_client.hpp"
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

Fill AlpacaPaperAdapter::sim_at_live_price(const risk::OrderProposal& o,
                                           const std::string& note) {
    // Simulated fill at the live market price carried on the proposal.
    Fill f = make_paper_fill(o, "paper", 0.0001);
    f.note = note;
    return f;
}

Fill AlpacaPaperAdapter::place(const risk::OrderProposal& o) {
    if (strategy_ == "sim_live_price") {
        return sim_at_live_price(o, "paper (sim @ live price)");
    }

    // strategy_ is "api" or "auto": try the Alpaca paper API via the bridge.
    std::ostringstream body;
    body << "{\"symbol\":\"" << util::json_escape(o.symbol) << "\","
         << "\"side\":\"" << util::json_escape(o.side) << "\","
         << "\"qty\":" << o.qty << ","
         << "\"price\":" << o.price << "}";
    auto resp = bridge::http_post_json(bridge_host_, bridge_port_,
                                       "/execute/alpaca_paper", body.str());
    if (resp) {
        std::string status = bridge::json_get_string(*resp, "status", "");
        if (status == "ok") {
            Fill f;
            f.venue = o.venue;
            f.symbol = o.symbol;
            f.side = o.side;
            f.mode = "paper";
            f.qty = o.qty;
            // Use the broker-reported fill price/qty when present.
            double fp = bridge::json_get_number(*resp, "filled_price", o.price);
            double fq = bridge::json_get_number(*resp, "filled_qty", o.qty);
            if (fq > 0.0) f.qty = fq;
            f.price = fp > 0.0 ? fp : o.price;
            f.notional = f.qty * f.price;
            f.fee = 0.0;  // Alpaca paper equities are commission-free.
            f.ts = util::now_iso8601();
            f.executed = true;
            std::string id = bridge::json_get_string(*resp, "order_id", "");
            f.note = "alpaca paper API" + (id.empty() ? "" : " (id=" + id + ")");
            return f;
        }
    }

    // API unreachable / unauthorized / geo-blocked.
    if (strategy_ == "api") {
        // Even in explicit-api mode, keep paper trading alive with a clearly
        // marked sim fill rather than silently dropping the order.
        return sim_at_live_price(
            o, "paper (sim @ live price; alpaca paper API unavailable)");
    }
    // "auto": documented geo-fallback.
    return sim_at_live_price(
        o, "paper (sim @ live price; alpaca paper unavailable)");
}

Fill CoinbaseSimAdapter::place(const risk::OrderProposal& o) {
    // Coinbase paper/sim: immediate simulated fill at the proposal price.
    // TODO: Coinbase — add a real (disabled-by-default) live adapter later.
    return make_paper_fill(o, "paper", 0.0001);
}

Fill IbkrLiveAdapter::place(const risk::OrderProposal& o) {
    // IBKR is live only. This is reached only through the gated Live branch with
    // live enabled, which stays off this session, so it does not execute now.
    // When enabled, it forwards the order to IB Gateway over the Python bridge.
    // A missing bridge or a dropped Gateway session fails the order safely and
    // is logged by the caller. It never simulates or silently fills.
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

    std::ostringstream body;
    body << "{\"symbol\":\"" << util::json_escape(o.symbol) << "\","
         << "\"side\":\"" << util::json_escape(o.side) << "\","
         << "\"qty\":" << o.qty << ","
         << "\"price\":" << o.price << "}";
    auto resp = bridge::http_post_json(bridge_host_, bridge_port_,
                                       "/execute/ibkr_live", body.str());
    if (!resp) {
        f.note = "IBKR live failed safely: IB Gateway bridge unreachable";
        return f;
    }
    std::string status = bridge::json_get_string(*resp, "status", "");
    if (status != "ok") {
        std::string err = bridge::json_get_string(*resp, "error", "refused");
        f.note = "IBKR live failed safely: " + err;
        return f;
    }
    double fp = bridge::json_get_number(*resp, "filled_price", o.price);
    double fq = bridge::json_get_number(*resp, "filled_qty", o.qty);
    if (fq > 0.0) f.qty = fq;
    f.price = fp > 0.0 ? fp : o.price;
    f.notional = f.qty * f.price;
    f.executed = true;
    std::string id = bridge::json_get_string(*resp, "order_id", "");
    f.note = "IBKR live fill" + (id.empty() ? "" : " (id=" + id + ")");
    return f;
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
