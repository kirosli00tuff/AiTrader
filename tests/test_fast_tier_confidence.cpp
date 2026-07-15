// Fast-tier native confidence composition test.
//
// The two-tier design runs a small, low-conviction native entry on the FAST
// tier: native signal + RiskGate only, NO council. The three LLM council slots
// are therefore NOT consulted and hold only neutral in-process mocks (~0.5).
//
// Bug (council_ran = true, the old behavior): the gate confidence blended those
// neutral council mocks in. Capped at its floor share, a genuine native
// conviction (0.7+) plus a couple of aligned advisory factors gets dragged below
// the RiskGate min_confidence floor (0.65), so EVERY fast-tier entry is
// structurally blocked with "confidence below min_confidence_default".
//
// Fix (council_ran = false): the gate confidence/edge are recomposed from the
// factors that actually produced a signal (native rule_based + real advisory),
// so the gate sees the native signal's real confidence. Bias and agreement stay
// from the full set. This never touches the RiskGate or its thresholds.
#include <cmath>
#include <vector>

#include "signal_engine/factor_engine.hpp"
#include "test_util.hpp"

using namespace mal::signal_engine;

// The RiskGate min_confidence_default the gate compares against (config default).
static constexpr double kMinConfidence = 0.65;
// The rule_based weight floor the engine passes to compose_gate_verdict.
static constexpr double kRuleFloor = 0.35;

int main() {
    WeightState w;
    w.set_from_map({{"rule_based", 0.20},
                    {"llm_primary", 0.25},
                    {"llm_secondary", 0.15},
                    {"llm_tertiary", 0.10},
                    {"dnn_advisory", 0.15},
                    {"whale_signal", 0.15}});

    // is_council_factor names exactly the three LLM slots.
    maltest::check(is_council_factor("llm_primary") &&
                       is_council_factor("llm_secondary") &&
                       is_council_factor("llm_tertiary"),
                   "is_council_factor names the three LLM slots");
    maltest::check(!is_council_factor("rule_based") &&
                       !is_council_factor("dnn_advisory") &&
                       !is_council_factor("whale_signal"),
                   "is_council_factor excludes native and non-LLM advisory");

    // --- Case 1: genuine native setup with aligned advisory, council skipped. ---
    // rule_based conviction is genuinely sufficient (0.775 = 0.7 + 0.3*str), the
    // real advisory (dnn/whale) agrees; the three LLM slots are neutral mocks the
    // fast tier never consulted.
    std::vector<FactorSignal> good = {
        {"rule_based", 0.55, 0.775, 0.075},  // real native conviction
        {"llm_primary", 0.05, 0.50, 0.01},   // un-consulted neutral council mock
        {"llm_secondary", 0.05, 0.50, 0.01},
        {"llm_tertiary", 0.05, 0.50, 0.01},
        {"dnn_advisory", 0.40, 0.72, 0.04},  // real advisory, aligned long
        {"whale_signal", 0.30, 0.68, 0.02},  // real advisory, aligned long
    };

    auto blended =  // council_ran = true: the old full blend (the bug)
        compose_gate_verdict(good, w, /*native_feeds_gate=*/true, 0.05, kRuleFloor,
                             /*council_ran=*/true);
    auto skipped =  // council_ran = false: recomposed without the council mocks
        compose_gate_verdict(good, w, /*native_feeds_gate=*/true, 0.05, kRuleFloor,
                             /*council_ran=*/false);

    maltest::check(blended.confidence < kMinConfidence,
                   "BUG reproduced: full blend drags a genuine native entry below "
                   "the floor (would be blocked)");
    maltest::check(skipped.confidence >= kMinConfidence,
                   "FIX: council-skipped confidence clears the floor (native "
                   "signal reports its real confidence)");
    maltest::check(skipped.confidence > blended.confidence,
                   "the un-consulted council mocks were what dragged confidence "
                   "down");
    maltest::check(std::fabs(skipped.bias - blended.bias) < 1e-9,
                   "direction (bias) identical: only confidence/edge recomposed");
    maltest::check(skipped.agreement_count == blended.agreement_count,
                   "agreement count identical: composition never eases agreement");

    // --- Case 2: genuinely weak advisory, council skipped. The fix does NOT ---
    // force trades. The native rule_based is fine but the real advisory that DID
    // run on the fast tier is weak, so the composed confidence stays below the
    // floor and the entry is correctly blocked (genuine selectivity).
    std::vector<FactorSignal> weak = {
        {"rule_based", 0.55, 0.775, 0.075},
        {"llm_primary", 0.05, 0.50, 0.01},
        {"llm_secondary", 0.05, 0.50, 0.01},
        {"llm_tertiary", 0.05, 0.50, 0.01},
        {"dnn_advisory", 0.10, 0.30, 0.01},  // real advisory, weak
        {"whale_signal", 0.05, 0.30, 0.01},  // real advisory, weak
    };
    auto weak_skipped =
        compose_gate_verdict(weak, w, /*native_feeds_gate=*/true, 0.05, kRuleFloor,
                             /*council_ran=*/false);
    maltest::check(weak_skipped.confidence < kMinConfidence,
                   "no forced trades: a genuinely weak advisory read still blocks "
                   "on the fast tier");

    // --- Case 3: council tier unchanged. council_ran = true equals the plain ---
    // full-ensemble combine, so the real council-tier path is untouched.
    auto base = combine(good, w, 0.05, kRuleFloor);
    maltest::check(std::fabs(base.confidence - blended.confidence) < 1e-9,
                   "council_ran=true equals the full-ensemble combine (council "
                   "tier untouched)");

    return maltest::report("fast_tier_confidence");
}
