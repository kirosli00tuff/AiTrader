// Market AI Lab — account / venue / credential / mode state machine.
//
// Owns the per-venue runtime state: current mode, whether credentials are
// connected, kill-switch latch, consecutive-loss tracking, and the live-enable
// transition. Live can ONLY be enabled via `try_enable_live`, which requires the
// approval gate to have passed AND credentials present. Disabled by default.
#pragma once

#include <map>
#include <string>
#include <vector>

#include "config/config.hpp"

namespace mal::account {

struct VenueState {
    std::string name;
    config::VenueMode mode = config::VenueMode::Paper;
    bool live_enabled = false;
    bool credentials_connected = false;
    bool kill_switch_tripped = false;
    int consecutive_losses = 0;
    std::string cooldown_until_ts;
    double equity = 0.0;
    double realized_pnl_today = 0.0;
};

class AccountManager {
public:
    explicit AccountManager(const config::Config& cfg);

    const std::map<std::string, VenueState>& venues() const { return venues_; }
    VenueState* find(const std::string& venue);

    void set_credentials_connected(const std::string& venue, bool connected);
    void set_mode(const std::string& venue, config::VenueMode mode);

    // Attempt to enable live for a venue. Returns false (with reason) unless:
    //  - approval gate passed (approval_passed=true),
    //  - credentials are connected,
    //  - kill switch is not tripped.
    // This is the ONLY path to live; default state is live disabled.
    bool try_enable_live(const std::string& venue, bool approval_passed,
                         std::string& reason);

    void disable_live(const std::string& venue);

    void record_trade_outcome(const std::string& venue, bool win);
    void trip_kill_switch(const std::string& venue);
    void manual_resume(const std::string& venue);

private:
    std::map<std::string, VenueState> venues_;
};

}  // namespace mal::account
