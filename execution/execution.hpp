// Market AI Lab — execution mode router + venue adapters.
//
// The mode router decides, per venue, whether an approved order is: shown only
// (recommendation_only), simulated (paper), or sent live (live — disabled by
// default, gated). Live adapters are present but refuse to operate unless
// explicitly enabled. Binance + IBKR live paths are intentionally incomplete
// (TODO markers) per the build spec.
#pragma once

#include <memory>
#include <optional>
#include <string>

#include "config/config.hpp"
#include "risk/risk_gate.hpp"

namespace mal::execution {

struct Fill {
    std::string venue, symbol, side, mode;
    double qty = 0, price = 0, notional = 0, fee = 0;
    std::string ts;
    bool executed = false;
    std::string note;
};

// One venue's adapter (paper or live implementation).
class VenueAdapter {
public:
    virtual ~VenueAdapter() = default;
    virtual std::string name() const = 0;
    virtual bool is_live() const = 0;
    // Place an order. Implementations must honor `enabled`/live gating.
    virtual Fill place(const risk::OrderProposal& o) = 0;
};

// --- Paper adapters (used in the demo) ---

class PolymarketPaperAdapter : public VenueAdapter {
public:
    std::string name() const override { return "polymarket-paper-trader"; }
    bool is_live() const override { return false; }
    Fill place(const risk::OrderProposal& o) override;
};

class AlpacaPaperAdapter : public VenueAdapter {
public:
    std::string name() const override { return "alpaca_paper"; }
    bool is_live() const override { return false; }
    Fill place(const risk::OrderProposal& o) override;
};

class BinanceSimAdapter : public VenueAdapter {
public:
    std::string name() const override { return "binance_sim"; }
    bool is_live() const override { return false; }
    Fill place(const risk::OrderProposal& o) override;
};

class IbkrSimPlaceholderAdapter : public VenueAdapter {
public:
    std::string name() const override { return "ibkr_sim_placeholder"; }
    bool is_live() const override { return false; }
    Fill place(const risk::OrderProposal& o) override;
};

// --- Live adapters (DISABLED by default; refuse unless explicitly enabled) ---

class DisabledLiveAdapter : public VenueAdapter {
public:
    explicit DisabledLiveAdapter(std::string venue) : venue_(std::move(venue)) {}
    std::string name() const override { return venue_ + "_live(disabled)"; }
    bool is_live() const override { return true; }
    Fill place(const risk::OrderProposal& o) override;  // always refuses

private:
    std::string venue_;
};

// Routes an approved order to the right adapter based on the venue mode.
class ModeRouter {
public:
    // route: returns a Fill describing what happened. Caller must have already
    // passed the order through RiskGate; this only handles mode dispatch.
    Fill route(config::VenueMode mode, VenueAdapter& paper_adapter,
               VenueAdapter& live_adapter, const risk::OrderProposal& o,
               bool live_enabled);
};

}  // namespace mal::execution
