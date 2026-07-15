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

// Two-tier execution (Task 5). FAST = native signal + RiskGate only, NO council.
// COUNCIL = gate then council then RiskGate. A candidate is FAST only when both
// its notional and its native conviction are at/below the configured thresholds.
enum class Tier { Fast, Council };

// Mutable gate state carried by the engine across ticks.
struct CouncilGateState {
    std::string utc_day;                          // current UTC day bucket
    int calls_today = 0;                          // full-council calls used today
    std::string utc_month;                        // current UTC month bucket (YYYY-MM)
    int calls_month = 0;                          // full-council calls used this month
    std::map<std::string, long> last_call_epoch;  // per-symbol last council (epoch s)
};

// Roll the daily budget over when the UTC day changes. Cooldown timestamps are
// wall-clock based and intentionally kept across the day boundary.
void reset_if_new_day(CouncilGateState& state, const std::string& utc_day);

// Roll the monthly spend tally over when the UTC month (YYYY-MM) changes.
void reset_if_new_month(CouncilGateState& state, const std::string& utc_month);

// Which tier a candidate takes. FAST when notional <= fast_tier_max_notional_pct
// of equity AND conviction <= fast_tier_max_conviction, else COUNCIL. With the
// swing defaults (0.0 / 0.0) no real entry is ever FAST, so swing is unchanged.
Tier decide_tier(const config::CouncilConfig& cfg, double notional, double equity,
                 double conviction);

// True when the estimated council spend (calls times council_est_cost_per_call_usd)
// has reached a configured daily or monthly ceiling. A 0.0 ceiling is disabled.
// When true the engine forces the fast tier (skips the council), logged.
bool spend_ceiling_reached(const config::CouncilConfig& cfg,
                           const CouncilGateState& state);

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
