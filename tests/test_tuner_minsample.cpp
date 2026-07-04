// Unit tests for the adaptive tuner's minimum-sample gate (Task 3 / Task 11).
//
// The native real-fill path must accumulate kMinClosedTradesForAdapt (30) CLOSED
// trades before the adaptive layer is allowed to nudge weights; the bootstrap
// sim path only needs one trade. This locks that boundary as a pure predicate so
// the "don't adapt on thin evidence" rule can never silently regress. No I/O.
#include "learning/adapt_gate.hpp"

#include "tests/test_util.hpp"

using namespace mal;
using maltest::check;
using learning::has_enough_samples_to_adapt;
using learning::kMinClosedTradesForAdapt;

int main() {
    // The published threshold is exactly 30 (single source of truth for the
    // engine run loop and this test).
    check(kMinClosedTradesForAdapt == 30,
          "minimum closed trades before adapting is 30");

    // --- Native real-fill path (bootstrap_sim = false) ------------------
    {
        const bool sim = false;
        // Below the threshold: never adapt, regardless of the sim trade count.
        check(!has_enough_samples_to_adapt(sim, /*trades=*/999, /*closed=*/0),
              "native: 0 closed trades => do NOT adapt");
        check(!has_enough_samples_to_adapt(sim, 999, 29),
              "native: 29 closed trades (one short) => do NOT adapt");
        // At and above the threshold: adapt.
        check(has_enough_samples_to_adapt(sim, 0, 30),
              "native: exactly 30 closed trades => adapt");
        check(has_enough_samples_to_adapt(sim, 0, 31),
              "native: 31 closed trades => adapt");
        check(has_enough_samples_to_adapt(sim, 0, 1000),
              "native: many closed trades => adapt");
        // On the native path the (bootstrap) trade_count is irrelevant.
        check(!has_enough_samples_to_adapt(sim, 5, 5),
              "native: sim trade_count is ignored; 5 closed < 30 => do NOT adapt");
    }

    // --- Bootstrap-sim path (bootstrap_sim = true) ----------------------
    {
        const bool sim = true;
        // Needs at least one trade; closed_trade_count is irrelevant here.
        check(!has_enough_samples_to_adapt(sim, /*trades=*/0, /*closed=*/999),
              "bootstrap: 0 sim trades => do NOT adapt (closed count ignored)");
        check(has_enough_samples_to_adapt(sim, 1, 0),
              "bootstrap: 1 sim trade => adapt even with 0 closed trades");
        check(has_enough_samples_to_adapt(sim, 100, 0),
              "bootstrap: many sim trades => adapt");
    }

    return maltest::report("tuner_minsample");
}
