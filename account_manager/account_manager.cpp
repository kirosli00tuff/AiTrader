#include "account_manager/account_manager.hpp"

namespace mal::account {

AccountManager::AccountManager(const config::Config& cfg) {
    for (const auto& v : cfg.venues) {
        VenueState st;
        st.name = v.name;
        st.mode = v.mode;
        st.live_enabled = false;  // SAFETY: never live at startup
        st.credentials_connected = false;
        st.equity = cfg.system.starting_paper_balance;
        venues_[v.name] = st;
    }
}

VenueState* AccountManager::find(const std::string& venue) {
    auto it = venues_.find(venue);
    return it == venues_.end() ? nullptr : &it->second;
}

void AccountManager::set_credentials_connected(const std::string& venue,
                                               bool connected) {
    if (auto* v = find(venue)) v->credentials_connected = connected;
}

void AccountManager::set_mode(const std::string& venue, config::VenueMode mode) {
    auto* v = find(venue);
    if (!v) return;
    // Switching to live is not permitted through set_mode — must go via
    // try_enable_live so the approval gate is enforced.
    if (mode == config::VenueMode::Live && !v->live_enabled) return;
    v->mode = mode;
}

bool AccountManager::try_enable_live(const std::string& venue,
                                     bool approval_passed, std::string& reason) {
    auto* v = find(venue);
    if (!v) {
        reason = "unknown venue";
        return false;
    }
    if (!approval_passed) {
        reason = "live approval gate not passed";
        return false;
    }
    if (!v->credentials_connected) {
        reason = "credentials not connected";
        return false;
    }
    if (v->kill_switch_tripped) {
        reason = "kill switch tripped";
        return false;
    }
    v->live_enabled = true;
    v->mode = config::VenueMode::Live;
    reason = "live enabled";
    return true;
}

void AccountManager::disable_live(const std::string& venue) {
    if (auto* v = find(venue)) {
        v->live_enabled = false;
        if (v->mode == config::VenueMode::Live) v->mode = config::VenueMode::Paper;
    }
}

void AccountManager::record_trade_outcome(const std::string& venue, bool win) {
    if (auto* v = find(venue)) {
        if (win) v->consecutive_losses = 0;
        else v->consecutive_losses++;
    }
}

void AccountManager::trip_kill_switch(const std::string& venue) {
    if (auto* v = find(venue)) {
        v->kill_switch_tripped = true;
        // Tripping kill switch immediately revokes live.
        v->live_enabled = false;
        if (v->mode == config::VenueMode::Live) v->mode = config::VenueMode::Paper;
    }
}

void AccountManager::manual_resume(const std::string& venue) {
    if (auto* v = find(venue)) {
        v->kill_switch_tripped = false;
        v->consecutive_losses = 0;
    }
}

}  // namespace mal::account
