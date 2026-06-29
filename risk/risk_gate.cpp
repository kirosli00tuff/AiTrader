#include "risk/risk_gate.hpp"

namespace mal::risk {

namespace {
double map_get(const std::map<std::string, double>& m, const std::string& k) {
    auto it = m.find(k);
    return it == m.end() ? 0.0 : it->second;
}
int map_get_i(const std::map<std::string, int>& m, const std::string& k) {
    auto it = m.find(k);
    return it == m.end() ? 0 : it->second;
}
}  // namespace

Decision RiskGate::evaluate(const OrderProposal& o,
                            const PortfolioState& s) const {
    Decision d;
    auto fail = [&](const std::string& why) { d.failed_checks.push_back(why); };

    const double equity = s.equity > 0 ? s.equity : 1.0;  // guard div-by-zero

    // --- Hard global stops first (kill switch, cooldown, manual resume) ---
    if (s.kill_switch_tripped)
        fail("kill_switch tripped — trading halted");
    if (s.manual_resume_pending && limits_.manual_resume_required_after_kill_switch)
        fail("manual resume required after kill switch");
    if (s.in_cooldown)
        fail("in cooldown after loss breach");

    // --- Daily loss limits (total + per-venue) ---
    // realized_pnl_today is negative on losses; compare loss against limit.
    const double daily_loss_total = -s.realized_pnl_today_total;  // positive when losing
    if (daily_loss_total >= limits_.max_daily_loss_total_pct * equity)
        fail("max_daily_loss_total_pct breached");

    const double venue_loss =
        -map_get(s.realized_pnl_today_per_venue, o.venue);
    if (venue_loss >= limits_.max_daily_loss_per_venue_pct * equity)
        fail("max_daily_loss_per_venue_pct breached for " + o.venue);

    // --- Per-trade risk cap ---
    if (o.notional > limits_.max_trade_risk_pct_of_equity * equity)
        fail("trade notional exceeds max_trade_risk_pct_of_equity");

    // --- Total open risk cap ---
    if (s.open_risk_total + o.notional > limits_.max_total_open_risk_pct * equity)
        fail("would exceed max_total_open_risk_pct");

    // --- Position-count caps ---
    if (s.open_positions_total + 1 > limits_.max_open_positions_total)
        fail("would exceed max_open_positions_total");
    if (map_get_i(s.open_positions_per_venue, o.venue) + 1 >
        limits_.max_open_positions_per_venue)
        fail("would exceed max_open_positions_per_venue for " + o.venue);

    // --- Exposure caps (symbol / market / category) ---
    if (map_get(s.exposure_per_symbol, o.symbol) + o.notional >
        limits_.max_exposure_per_symbol_pct * equity)
        fail("would exceed max_exposure_per_symbol_pct for " + o.symbol);
    if (!o.market.empty() &&
        map_get(s.exposure_per_market, o.market) + o.notional >
            limits_.max_exposure_per_market_pct * equity)
        fail("would exceed max_exposure_per_market_pct for " + o.market);
    if (!o.category.empty() &&
        map_get(s.exposure_per_category, o.category) + o.notional >
            limits_.max_exposure_per_category_pct * equity)
        fail("would exceed max_exposure_per_category_pct for " + o.category);

    // --- Consecutive losses ---
    if (s.consecutive_losses >= limits_.max_consecutive_losses)
        fail("max_consecutive_losses reached");

    // --- Quality gates (confidence / edge / agreement / staleness) ---
    if (o.confidence < limits_.min_confidence_default)
        fail("confidence below min_confidence_default");
    if (o.edge < limits_.min_edge_default)
        fail("edge below min_edge_default");
    if (o.model_agreement_count < limits_.required_model_agreement_count)
        fail("insufficient model agreement");
    if (o.signal_age_minutes > limits_.stale_signal_reject_minutes)
        fail("signal too stale");

    // --- Live-specific hard stop ---
    if (o.is_live && limits_.hard_stop_live_if_loss_breach &&
        daily_loss_total >= limits_.max_daily_loss_total_pct * equity)
        fail("live hard-stop: daily loss breach");

    if (d.failed_checks.empty()) {
        d.allowed = true;
        d.reason = "OK";
    } else {
        d.allowed = false;
        d.reason = d.failed_checks.front();  // primary reason
    }
    return d;
}

bool KillSwitch::trip(const std::string& reason) {
    if (!enabled_) return false;
    if (tripped_) return false;
    tripped_ = true;
    reason_ = reason;
    return true;
}

bool KillSwitch::manual_resume() {
    if (!tripped_) return false;
    // Manual resume always permitted to clear a tripped switch; if manual
    // resume was NOT required, this is still a valid (explicit) clear.
    tripped_ = false;
    reason_.clear();
    return true;
}

}  // namespace mal::risk
