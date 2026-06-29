// Market AI Lab — Layer 1: Static Safety (RiskGate).
//
// FINAL AUTHORITY. This gate is the last check before any order can route to
// execution. It is pure and deterministic: given an order proposal and the
// current portfolio/risk state, it returns an explicit allow/deny + reason.
//
// Nothing — not LLMs, the DNN/RL factor, the whale signal, the adaptive layer,
// nor any execution adapter — may bypass it. It only ever *denies* on the basis
// of the immutable hard limits in `RiskConfig`; it can never be made more
// permissive by upstream advisory layers.
#pragma once

#include <string>
#include <vector>

#include "config/config.hpp"

namespace mal::risk {

// Proposed order to evaluate (already sized by upstream layers, subject to caps).
struct OrderProposal {
    std::string venue;
    std::string symbol;
    std::string market;
    std::string category;
    std::string side;        // buy | sell
    double qty = 0.0;
    double price = 0.0;
    double notional = 0.0;   // qty * price
    double confidence = 0.0; // combined confidence [0,1]
    double edge = 0.0;       // combined expected edge
    int model_agreement_count = 0;
    int signal_age_minutes = 0;
    bool is_live = false;    // true if routing to a live venue
};

// Mutable risk/portfolio state the gate reads (never mutates).
struct PortfolioState {
    double equity = 0.0;                 // current total equity
    double start_of_day_equity = 0.0;    // for daily-loss checks
    double realized_pnl_today_total = 0.0;
    std::map<std::string, double> realized_pnl_today_per_venue;
    double open_risk_total = 0.0;        // sum of open position risk (notional-based)
    int open_positions_total = 0;
    std::map<std::string, int> open_positions_per_venue;
    std::map<std::string, double> exposure_per_symbol;   // notional
    std::map<std::string, double> exposure_per_market;
    std::map<std::string, double> exposure_per_category;
    int consecutive_losses = 0;
    bool kill_switch_tripped = false;
    bool in_cooldown = false;
    bool manual_resume_pending = false;  // kill switch requires manual resume
};

struct Decision {
    bool allowed = false;
    std::string reason;          // human-readable; "OK" when allowed
    std::string layer = "Layer1";
    // All individual reasons that contributed to a denial (audit detail).
    std::vector<std::string> failed_checks;
};

// The deterministic gate. Construction binds the immutable hard limits.
class RiskGate {
public:
    explicit RiskGate(config::RiskConfig limits) : limits_(std::move(limits)) {}

    // Evaluate a proposal against state. Pure: no I/O, no mutation.
    Decision evaluate(const OrderProposal& o, const PortfolioState& s) const;

    const config::RiskConfig& limits() const { return limits_; }

private:
    config::RiskConfig limits_;
};

// Kill-switch / hard-stop state machine. Separate from the pure gate so the
// gate stays side-effect free. This object owns the latch + manual-resume rule.
class KillSwitch {
public:
    KillSwitch(bool enabled, bool manual_resume_required)
        : enabled_(enabled), manual_resume_required_(manual_resume_required) {}

    bool tripped() const { return tripped_; }
    bool manual_resume_pending() const { return tripped_ && manual_resume_required_; }

    // Trip the switch (latches). Returns true if state changed.
    bool trip(const std::string& reason);
    const std::string& trip_reason() const { return reason_; }

    // Manual resume: only clears if a manual resume is what's required, or if
    // manual resume is not required (auto-clearable). Returns true if cleared.
    bool manual_resume();

    bool enabled() const { return enabled_; }

private:
    bool enabled_;
    bool manual_resume_required_;
    bool tripped_ = false;
    std::string reason_;
};

}  // namespace mal::risk
