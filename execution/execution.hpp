// Market AI Lab — execution mode router + venue adapters.
//
// The mode router decides, per venue, whether an approved order is shown only
// (recommendation_only), simulated (paper), or sent live (live, disabled by
// default, gated). Live adapters are present but refuse to operate unless
// explicitly enabled.
//
// Venue roles. Alpaca handles all paper trading and paper market data. Alpaca
// has no live path and must never be wired to one. Coinbase is paper/sim only.
// IBKR handles live trading only. IBKR routes through the gated Live branch and
// stays disabled behind the approval gate.
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

// --- Paper adapters ---

// Alpaca paper-trading adapter.
//
// Strategy (`paper_execution` from config):
//   "api"            — submit the order to the Alpaca PAPER trading API via the
//                      Python bridge (POST /execute/alpaca_paper).
//   "sim_live_price" — never call the API; simulate an immediate fill at the
//                      live market price carried on the order proposal.
//   "auto" (default) — try the API; if the bridge is unreachable, unauthorized,
//                      or geo-blocked, fall back to a sim-at-live-price fill so
//                      paper trading keeps running everywhere (e.g. Canada).
//
// SAFETY: this is paper only — it targets paper-api.alpaca.markets. It never
// touches a live brokerage account.
class AlpacaPaperAdapter : public VenueAdapter {
public:
    AlpacaPaperAdapter(std::string strategy = "auto",
                       std::string bridge_host = "127.0.0.1",
                       int bridge_port = 8765)
        : strategy_(std::move(strategy)),
          bridge_host_(std::move(bridge_host)),
          bridge_port_(bridge_port) {}
    std::string name() const override { return "alpaca_paper"; }
    bool is_live() const override { return false; }
    Fill place(const risk::OrderProposal& o) override;

private:
    Fill sim_at_live_price(const risk::OrderProposal& o, const std::string& note);
    std::string strategy_;
    std::string bridge_host_;
    int bridge_port_;
};

// Coinbase paper/sim adapter. Paper-only: simulates a fill at the proposal
// price. Live Coinbase execution is intentionally not implemented (disabled),
// and credential env vars (COINBASE_API_KEY/SECRET) are reserved only.
class CoinbaseSimAdapter : public VenueAdapter {
public:
    std::string name() const override { return "coinbase_sim"; }
    bool is_live() const override { return false; }
    Fill place(const risk::OrderProposal& o) override;
};

// IBKR live adapter. IBKR is live only. It connects to a locally run IB Gateway
// session that the operator starts and authenticates. No IBKR credentials pass
// through this app. This is a LIVE adapter. It routes only through the mode
// router Live branch, which stays gated by the four safety mechanisms, so it
// cannot execute until the operator passes the approval gate and turns live on.
// It places orders over the Python bridge (POST /execute/ibkr_live), which talks
// to IB Gateway. A dropped Gateway session fails the order safely and logs it.
class IbkrLiveAdapter : public VenueAdapter {
public:
    IbkrLiveAdapter(std::string bridge_host = "127.0.0.1", int bridge_port = 8765)
        : bridge_host_(std::move(bridge_host)), bridge_port_(bridge_port) {}
    std::string name() const override { return "ibkr_live"; }
    bool is_live() const override { return true; }
    Fill place(const risk::OrderProposal& o) override;

private:
    std::string bridge_host_;
    int bridge_port_;
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
