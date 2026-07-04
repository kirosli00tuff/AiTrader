// Market AI Lab — adaptive-tuning sample gate (pure decision logic).
//
// The adaptive tuner (Layer 2) may only nudge weights once the loop has
// accumulated enough OUTCOMES to trust factor-performance estimates. On the
// native real-fill path that means a minimum number of CLOSED trades (Task 3);
// the bootstrap-sim path uses a lighter "any trade happened" gate. Extracted
// here as a pure predicate so the rule is unit-testable without constructing a
// full Engine (SQLite DAO, accounts, config). Header-only; no I/O, no state.
#pragma once

namespace mal::learning {

// Minimum CLOSED native trades before the adaptive tuner may nudge weights.
// Single source of truth: the engine's run loop and the tests both read this.
inline constexpr long kMinClosedTradesForAdapt = 30;

// Has the loop seen enough outcomes to justify an adaptive weight update?
// Mirrors Engine::maybe_adapt's sample-count precondition exactly:
//   * bootstrap-sim path : at least one simulated trade has occurred, else wait;
//   * native real-fill    : at least kMinClosedTradesForAdapt CLOSED trades.
// This gate never loosens a risk limit — it only decides WHEN to adapt, and the
// adaptive layer remains structurally unable to weaken any Layer-1 hard limit.
inline bool has_enough_samples_to_adapt(bool bootstrap_sim, long trade_count,
                                        long closed_trade_count) {
    if (bootstrap_sim) return trade_count > 0;
    return closed_trade_count >= kMinClosedTradesForAdapt;
}

}  // namespace mal::learning
