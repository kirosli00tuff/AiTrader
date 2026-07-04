// Market AI Lab — council cost-control gate (pure decision logic).
//
// The expensive LLM council runs ONLY on a native-strategy candidate ENTRY, and
// even then only after passing these cost controls (Task 4):
//   1. neutral-skip  — regime is neutral AND signal strength below a threshold
//   2. per-symbol cooldown — one full council per symbol per N minutes
//   3. daily budget  — at most council_daily_budget full-council calls per day
// This header is pure: the engine owns the mutable state + the actual Flash-gate
// / council HTTP calls; here we only decide and bookkeep. Every skip carries a
// reason the engine logs as a `council_skip` event.
#pragma once

#include <map>
#include <string>

#include "config/config.hpp"
#include "signal_engine/strategy.hpp"

namespace mal::signal_engine {

enum class CouncilDecision { Proceed, SkipNeutral, SkipCooldown, SkipBudget };
std::string council_decision_to_string(CouncilDecision d);

// Mutable gate state carried by the engine across ticks.
struct CouncilGateState {
    std::string utc_day;                          // current UTC day bucket
    int calls_today = 0;                          // full-council calls used today
    std::map<std::string, long> last_call_epoch;  // per-symbol last council (epoch s)
};

// Roll the daily budget over when the UTC day changes. Cooldown timestamps are
// wall-clock based and intentionally kept across the day boundary.
void reset_if_new_day(CouncilGateState& state, const std::string& utc_day);

// Pure decision for whether to run the full council on a candidate entry.
// Skip precedence: neutral-skip, then per-symbol cooldown, then daily budget.
// Does not mutate state.
CouncilDecision decide_council(const config::CouncilConfig& cfg,
                               const CouncilGateState& state,
                               strategy::Regime regime, double signal_strength,
                               const std::string& symbol, long now_epoch);

// Record that a full council call was made: consumes one budget unit and starts
// the per-symbol cooldown. Call only after decide_council returned Proceed.
void record_council_call(CouncilGateState& state, const std::string& symbol,
                         long now_epoch);

}  // namespace mal::signal_engine
