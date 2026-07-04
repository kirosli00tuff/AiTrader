#include "signal_engine/council_gate.hpp"

namespace mal::signal_engine {

std::string council_decision_to_string(CouncilDecision d) {
    switch (d) {
        case CouncilDecision::Proceed: return "proceed";
        case CouncilDecision::SkipNeutral: return "skip_neutral";
        case CouncilDecision::SkipCooldown: return "skip_cooldown";
        case CouncilDecision::SkipBudget: return "skip_budget";
    }
    return "proceed";
}

void reset_if_new_day(CouncilGateState& state, const std::string& utc_day) {
    if (state.utc_day != utc_day) {
        state.utc_day = utc_day;
        state.calls_today = 0;
    }
}

CouncilDecision decide_council(const config::CouncilConfig& cfg,
                               const CouncilGateState& state,
                               strategy::Regime regime, double signal_strength,
                               const std::string& symbol, long now_epoch) {
    // 1. Neutral-skip: no point paying for a council when the regime is neutral
    //    and the signal is weak.
    if (regime == strategy::Regime::Neutral &&
        signal_strength < cfg.neutral_skip_strength_threshold)
        return CouncilDecision::SkipNeutral;

    // 2. Per-symbol cooldown.
    auto it = state.last_call_epoch.find(symbol);
    if (it != state.last_call_epoch.end()) {
        long cooldown_s =
            static_cast<long>(cfg.per_symbol_council_cooldown_minutes) * 60;
        if (now_epoch - it->second < cooldown_s)
            return CouncilDecision::SkipCooldown;
    }

    // 3. Daily budget.
    if (state.calls_today >= cfg.council_daily_budget)
        return CouncilDecision::SkipBudget;

    return CouncilDecision::Proceed;
}

void record_council_call(CouncilGateState& state, const std::string& symbol,
                         long now_epoch) {
    ++state.calls_today;
    state.last_call_epoch[symbol] = now_epoch;
}

}  // namespace mal::signal_engine
